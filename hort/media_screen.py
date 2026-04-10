"""Screen media provider — wraps PlatformProvider as a MediaProvider.

Maps existing windows and desktop to the unified MediaSource model.
Pull-mode only (server captures on demand).
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from hort.media import MediaProvider, MediaSource

logger = logging.getLogger(__name__)


class ScreenProvider(MediaProvider):
    """Wraps the existing PlatformProvider + TargetRegistry as a MediaProvider.

    Sources:
    - Each window → ``source_type="window"``, ``source_id="window:{window_id}"``
    - Desktop composite → ``source_type="screen"``, ``source_id="screen:-1"``

    Always pull-mode: the stream loop calls ``capture_frame()`` at the
    configured FPS.
    """

    def list_sources(self) -> list[MediaSource]:
        """List all windows and desktop as MediaSources."""
        from hort.targets import TargetRegistry

        sources: list[MediaSource] = []
        registry = TargetRegistry.get()
        provider = registry.get_default()
        if provider is None:
            return sources

        for w in provider.list_windows():
            src_type = "screen" if w.source_type == "screen" else "window"
            sources.append(MediaSource(
                source_id=f"{src_type}:{w.window_id}",
                source_type=src_type,
                media_type="video",
                name=f"{w.owner_name} — {w.window_name}" if w.window_name else w.owner_name,
                metadata={
                    "window_id": w.window_id,
                    "owner_name": w.owner_name,
                    "window_name": w.window_name,
                    "bounds": {
                        "x": w.bounds.x, "y": w.bounds.y,
                        "width": w.bounds.width, "height": w.bounds.height,
                    },
                    "is_on_screen": w.is_on_screen,
                    "space_index": w.space_index,
                    "owner_pid": w.owner_pid,
                },
                push_mode=False,
            ))

        return sources

    def supports_viewport(self, source_id: str) -> bool:
        return True  # all screen/window sources support zoom/pan

    async def capture_frame(
        self, source_id: str, max_width: int = 1920, quality: int = 80,
    ) -> bytes | None:
        """Capture a window or desktop frame."""
        from hort.targets import TargetRegistry

        # Parse window_id from source_id
        parts = source_id.split(":", 1)
        if len(parts) != 2:
            return None
        try:
            window_id = int(parts[1])
        except ValueError:
            return None

        registry = TargetRegistry.get()
        provider = registry.get_default()
        if provider is None:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, provider.capture_window, window_id, max_width, quality,
        )
