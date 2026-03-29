"""LlmingLens — remote desktop viewer extension.

Provides screen streaming, window browsing, and input control as a proper
extension. Appears as a single card on the main grid with a live desktop
thumbnail preview. Click to enter the viewer submenu.

The extension uses the shared PlatformProvider infrastructure (screen capture,
window listing, input simulation) — same APIs other extensions can use.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin

logger = logging.getLogger(__name__)


class LlmingLens(PluginBase, ScheduledMixin):
    """Remote desktop viewer extension."""

    _preview: dict[str, Any] = {}

    def activate(self, config: dict[str, Any]) -> None:
        self._preview = {}
        self.log.info("LlmingLens activated")

    def deactivate(self) -> None:
        self.log.info("LlmingLens deactivated")

    def get_status(self) -> dict[str, Any]:
        """Return desktop preview for the grid card thumbnail."""
        return self._preview

    def capture_preview(self) -> None:
        """Scheduled job: capture desktop + top 3 window thumbnails.

        Runs in an executor thread (never blocks the event loop).
        """
        try:
            from hort.targets import TargetRegistry

            registry = TargetRegistry.get()
            provider = registry.get_default()
            if not provider:
                return

            from hort.screen import DESKTOP_WINDOW_ID

            # Desktop preview
            frame = provider.capture_window(DESKTOP_WINDOW_ID, 960, 60)
            desktop_b64 = base64.b64encode(frame).decode() if frame else ""

            # Top 3 window thumbnails (small, for the stacked preview)
            window_thumbs = []
            try:
                windows = provider.list_windows()
                # Skip Desktop entry and take first 3 real windows
                real_windows = [w for w in windows if w.window_id >= 0][:3]
                for w in real_windows:
                    thumb = provider.capture_window(w.window_id, 240, 40)
                    if thumb:
                        window_thumbs.append({
                            "id": w.window_id,
                            "name": w.owner_name,
                            "b64": base64.b64encode(thumb).decode(),
                        })
            except Exception:
                pass

            self._preview = {
                "preview": desktop_b64,
                "window_thumbs": window_thumbs,
            }
        except Exception as exc:
            self.log.debug("preview capture failed: %s", exc)
