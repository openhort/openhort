"""macOS Spaces (Mission Control desktops) detection and switching."""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import c_int32, c_void_p
from dataclasses import dataclass

import objc  # type: ignore[import-untyped]

_skylight = ctypes.cdll.LoadLibrary(
    "/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight"
)
_skylight.CGSMainConnectionID.restype = c_int32
_skylight.CGSCopyManagedDisplaySpaces.argtypes = [c_int32]
_skylight.CGSCopyManagedDisplaySpaces.restype = c_void_p
_cgs_conn: int = _skylight.CGSMainConnectionID()


@dataclass(frozen=True)
class SpaceInfo:
    """Information about a macOS Space/desktop."""

    index: int  # 1-based
    space_id: int
    is_current: bool


def _read_display_spaces() -> list[dict[str, object]]:  # pragma: no cover
    """Read live Space data via CGSCopyManagedDisplaySpaces (private API)."""
    ptr = _skylight.CGSCopyManagedDisplaySpaces(_cgs_conn)
    if not ptr:
        return []
    result: list[dict[str, object]] = objc.objc_object(c_void_p=ptr)
    return list(result)


def get_spaces() -> list[SpaceInfo]:
    """Get all Spaces for the main display with current space marked."""
    displays = _read_display_spaces()
    if not displays:
        return []

    display: dict[str, object] = displays[0]
    current_space: dict[str, int] = display.get("Current Space", {})  # type: ignore[assignment]
    cur_id: int = current_space.get("ManagedSpaceID", 0)
    raw_spaces: list[dict[str, int]] = display.get("Spaces", [])  # type: ignore[assignment]

    spaces: list[SpaceInfo] = []
    for i, sp in enumerate(raw_spaces):
        sid: int = sp.get("ManagedSpaceID", 0)
        spaces.append(SpaceInfo(
            index=i + 1,
            space_id=sid,
            is_current=sid == cur_id,
        ))
    return spaces


def get_current_space_index() -> int:
    """Get the 1-based index of the current Space."""
    for sp in get_spaces():
        if sp.is_current:
            return sp.index
    return 1


def get_space_count() -> int:
    """Get the total number of Spaces."""
    return len(get_spaces())


def _switch_space_keystroke(direction: str) -> None:  # pragma: no cover
    """Send Ctrl+Arrow keystroke to switch Space."""
    keycode = "124" if direction == "right" else "123"
    subprocess.run(
        [
            "osascript", "-e",
            f'tell application "System Events" to key code {keycode} using control down',
        ],
        capture_output=True,
        timeout=3,
    )


def _wait_for_space(target_index: int, timeout: float = 3.0) -> bool:  # pragma: no cover
    """Poll until the current Space matches target or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if get_current_space_index() == target_index:
            return True
        time.sleep(0.2)
    return False


def switch_to_space(target_index: int) -> bool:
    """Switch to the Space at the given 1-based index.

    Uses Ctrl+Arrow keystrokes to navigate. Waits for the switch
    to actually complete before returning.
    """
    current = get_current_space_index()
    total = get_space_count()

    if target_index < 1 or target_index > total:
        return False
    if target_index == current:
        return True

    diff = target_index - current
    direction = "right" if diff > 0 else "left"
    for _ in range(abs(diff)):
        _switch_space_keystroke(direction)

    _wait_for_space(target_index)
    return True
