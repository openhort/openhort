"""Target management — tracks available platform targets.

A "target" is a machine (local or remote) whose windows can be viewed
and controlled.  Each target has a ``PlatformProvider`` that handles
window listing, capture, input, and workspaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hort.ext.types import PlatformProvider


@dataclass(frozen=True)
class TargetInfo:
    """Describes an available target."""

    id: str
    name: str
    provider_type: str  # "macos", "linux-docker", "azure", ...
    status: str = "available"  # "available", "connecting", "error"


class TargetRegistry:
    """Tracks available platform targets.

    Singleton — use ``TargetRegistry.get()``.
    """

    _instance: TargetRegistry | None = None

    def __init__(self) -> None:
        self._targets: dict[str, TargetInfo] = {}
        self._providers: dict[str, PlatformProvider] = {}
        self._default_id: str = ""

    @classmethod
    def get(cls) -> TargetRegistry:
        """Get or create the singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def register(
        self, target_id: str, info: TargetInfo, provider: PlatformProvider
    ) -> None:
        """Register a target with its provider."""
        self._targets[target_id] = info
        self._providers[target_id] = provider
        if not self._default_id:
            self._default_id = target_id

    def remove(self, target_id: str) -> None:
        """Remove a target."""
        self._targets.pop(target_id, None)
        self._providers.pop(target_id, None)
        if self._default_id == target_id:
            self._default_id = next(iter(self._targets), "")

    def get_provider(self, target_id: str) -> PlatformProvider | None:
        """Get the provider for a target."""
        return self._providers.get(target_id)

    def get_default(self) -> PlatformProvider | None:
        """Get the default target's provider."""
        return self._providers.get(self._default_id)

    @property
    def default_id(self) -> str:
        """ID of the default target."""
        return self._default_id

    @default_id.setter
    def default_id(self, value: str) -> None:
        if value in self._targets:
            self._default_id = value

    def list_targets(self) -> list[TargetInfo]:
        """List all registered targets."""
        return list(self._targets.values())

    def get_info(self, target_id: str) -> TargetInfo | None:
        """Get target info by ID."""
        return self._targets.get(target_id)
