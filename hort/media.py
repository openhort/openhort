"""Unified media source abstraction — screens, cameras, audio, remote feeds.

Every streamable thing is a ``MediaSource``. Providers register sources
with the ``SourceRegistry``. The stream loop and UI query the registry
to discover and connect to sources.

Source lifecycle:
- **Always-on** (windows, desktop): ``is_active()`` always True, no start/stop
- **On-demand** (cameras): ``start_source()`` opens device, ``stop_source()`` closes.
  Ref-counted — multiple viewers share one capture session.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MediaSource:
    """A single streamable source — window, screen, camera, audio, etc."""

    source_id: str              # unique: "window:42", "screen:-1", "cam:FaceTime HD"
    source_type: str            # "screen", "window", "camera", "audio"
    media_type: str = "video"   # "video", "audio", "av"
    name: str = ""              # human label
    metadata: dict[str, Any] = field(default_factory=dict)
    push_mode: bool = False     # True = source pushes frames at its own rate


class MediaProvider(ABC):
    """Base for all media providers — screens, cameras, audio devices.

    Pull-mode sources (windows, screens):
        The stream loop calls ``capture_frame()`` at the configured FPS.

    Push-mode sources (cameras, remote feeds):
        The provider buffers frames internally. The stream loop calls
        ``capture_frame()`` which returns the latest buffered frame.
        ``start_source()`` / ``stop_source()`` manage the capture lifecycle.
    """

    @abstractmethod
    def list_sources(self) -> list[MediaSource]:
        """List available sources without activating them (zero resource cost)."""

    async def start_source(self, source_id: str) -> bool:
        """Activate a source (open camera, start capture). Ref-counted.

        No-op for always-on sources (windows, desktop). Returns True on success.
        """
        return True

    async def stop_source(self, source_id: str) -> None:
        """Deactivate a source (close camera). Ref-counted.

        No-op for always-on sources.
        """

    def is_active(self, source_id: str) -> bool:
        """Whether the source is currently producing frames."""
        return True  # windows/screens are always active

    @abstractmethod
    async def capture_frame(
        self, source_id: str, max_width: int = 1920, quality: int = 80,
    ) -> bytes | None:
        """Grab a single frame as WebP/JPEG bytes.

        Returns None if the source is not active or capture failed.
        """

    def supports_viewport(self, source_id: str) -> bool:
        """Whether this source supports viewport crop/zoom."""
        return False


class SourceRegistry:
    """Central registry of all media providers and their sources.

    The stream loop and WS commands query this to find providers and
    route capture requests.
    """

    _instance: SourceRegistry | None = None

    def __init__(self) -> None:
        self._providers: dict[str, MediaProvider] = {}  # provider_id → provider

    @classmethod
    def get(cls) -> SourceRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def register(self, provider_id: str, provider: MediaProvider) -> None:
        """Register a media provider."""
        self._providers[provider_id] = provider

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    def list_sources(self, source_type: str = "") -> list[MediaSource]:
        """List all sources across all providers, optionally filtered by type."""
        sources: list[MediaSource] = []
        for provider in self._providers.values():
            for src in provider.list_sources():
                if not source_type or src.source_type == source_type:
                    sources.append(src)
        return sources

    def find_provider(self, source_id: str) -> MediaProvider | None:
        """Find the provider that owns a source_id."""
        for provider in self._providers.values():
            for src in provider.list_sources():
                if src.source_id == source_id:
                    return provider
        return None

    def get_source(self, source_id: str) -> MediaSource | None:
        """Look up a single source by ID."""
        for provider in self._providers.values():
            for src in provider.list_sources():
                if src.source_id == source_id:
                    return src
        return None

    def get_provider(self, provider_id: str) -> MediaProvider | None:
        """Get a provider by its registration ID."""
        return self._providers.get(provider_id)
