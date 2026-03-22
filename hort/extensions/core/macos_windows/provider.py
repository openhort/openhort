"""macOS window management via Quartz, SkyLight, and ApplicationServices.

All macOS-specific imports are deferred to method bodies so this module
can be *defined* on any platform.  It will only fail at runtime if you
call a method on a non-macOS system.
"""

from __future__ import annotations

from typing import Any

from hort.ext.types import ExtensionBase, PlatformProvider, WorkspaceInfo
from hort.models import InputEvent, WindowBounds, WindowInfo


class MacOSWindowsExtension(ExtensionBase, PlatformProvider):
    """Unified macOS extension providing all platform capabilities.

    Inherits ``PlatformProvider`` (the unified ABC the server programs
    against) and ``ExtensionBase`` (lifecycle hooks).
    """

    # -- WindowProvider --

    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        from hort.windows import list_windows

        return list_windows(app_filter)

    def get_app_names(self) -> list[str]:
        from hort.windows import get_app_names

        return get_app_names()

    # -- CaptureProvider --

    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None:
        from hort.screen import capture_window

        return capture_window(window_id, max_width, quality)

    # -- InputProvider --

    def handle_input(
        self, event: InputEvent, bounds: WindowBounds, pid: int = 0
    ) -> None:
        from hort.input import handle_input

        handle_input(event, bounds, pid)

    def activate_app(
        self, pid: int, bounds: WindowBounds | None = None
    ) -> None:
        from hort.input import _activate_app

        _activate_app(pid, bounds)

    # -- WorkspaceProvider --

    def get_workspaces(self) -> list[WorkspaceInfo]:
        from hort.spaces import get_spaces

        return [
            WorkspaceInfo(index=s.index, is_current=s.is_current)
            for s in get_spaces()
        ]

    def get_current_index(self) -> int:
        from hort.spaces import get_current_space_index

        return get_current_space_index()

    def switch_to(self, target_index: int) -> bool:
        from hort.spaces import switch_to_space

        return switch_to_space(target_index)
