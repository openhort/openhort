"""macOS window listing and filtering via Quartz API."""

from __future__ import annotations

import ctypes
from ctypes import c_int32, c_void_p
from typing import Any

import objc  # type: ignore[import-untyped]
import Quartz  # type: ignore[import-untyped]
from Foundation import NSArray  # type: ignore[import-untyped]

from hort.models import WindowBounds, WindowInfo

_skylight = ctypes.cdll.LoadLibrary(
    "/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight"
)
_skylight.CGSMainConnectionID.restype = c_int32
_skylight.CGSCopyManagedDisplaySpaces.argtypes = [c_int32]
_skylight.CGSCopyManagedDisplaySpaces.restype = c_void_p
_skylight.CGSCopySpacesForWindows.argtypes = [c_int32, c_int32, c_void_p]
_skylight.CGSCopySpacesForWindows.restype = c_void_p
_cgs_conn: int = _skylight.CGSMainConnectionID()


def _raw_window_list() -> list[dict[str, Any]]:  # pragma: no cover
    """Get raw window info dicts from Quartz — ALL windows, all Spaces."""
    options = (
        Quartz.kCGWindowListOptionAll
        | Quartz.kCGWindowListExcludeDesktopElements
    )
    window_list = Quartz.CGWindowListCopyWindowInfo(
        options, Quartz.kCGNullWindowID
    )
    if window_list is None:
        return []
    return list(window_list)


def _get_space_index_map() -> dict[int, int]:  # pragma: no cover
    """Build a map from Space ID to 1-based index."""
    ptr = _skylight.CGSCopyManagedDisplaySpaces(_cgs_conn)
    if not ptr:
        return {}
    displays: list[dict[str, Any]] = objc.objc_object(c_void_p=ptr)
    if not displays:
        return {}
    raw_spaces: list[dict[str, int]] = displays[0].get("Spaces", [])
    return {
        sp.get("ManagedSpaceID", 0): i + 1
        for i, sp in enumerate(raw_spaces)
    }


def _get_window_space(window_id: int, space_map: dict[int, int]) -> int:  # pragma: no cover
    """Get the Space index for a single window ID."""
    wid_array = NSArray.arrayWithObject_(window_id)
    ptr = _skylight.CGSCopySpacesForWindows(
        _cgs_conn, 7, objc.pyobjc_id(wid_array)  # 7 = all spaces mask
    )
    if not ptr:
        return 0
    space_ids: list[int] = list(objc.objc_object(c_void_p=ptr))
    if space_ids:
        return space_map.get(space_ids[0], 0)
    return 0


def _parse_window(raw: dict[str, Any], space_index: int = 0) -> WindowInfo | None:
    """Parse a raw Quartz window dict into a WindowInfo model.

    Returns None if the window should be filtered out.
    """
    owner_name = raw.get("kCGWindowOwnerName", "")
    if not owner_name:
        return None

    bounds_dict = raw.get("kCGWindowBounds")
    if not bounds_dict:
        return None

    bounds = WindowBounds(
        x=float(bounds_dict.get("X", 0)),
        y=float(bounds_dict.get("Y", 0)),
        width=float(bounds_dict.get("Width", 0)),
        height=float(bounds_dict.get("Height", 0)),
    )

    if bounds.width <= 0 or bounds.height <= 0:
        return None

    layer = int(raw.get("kCGWindowLayer", 0))
    if layer != 0:
        return None

    window_name = raw.get("kCGWindowName") or ""

    # Filter out unnamed helper/utility windows (they clutter the list)
    if not window_name:
        return None

    return WindowInfo(
        window_id=int(raw.get("kCGWindowNumber", 0)),
        owner_name=str(owner_name),
        window_name=str(window_name),
        bounds=bounds,
        layer=layer,
        owner_pid=int(raw.get("kCGWindowOwnerPID", 0)),
        is_on_screen=bool(raw.get("kCGWindowIsOnscreen", True)),
        space_index=space_index,
    )


def list_windows(app_filter: str | None = None) -> list[WindowInfo]:
    """List macOS windows from all Spaces, optionally filtered by app name.

    Each window includes its space_index (1-based) indicating which
    Space it belongs to. Windows on the current Space have is_on_screen=True.

    The list always starts with a virtual "Desktop" entry (window_id=-1)
    that captures the entire screen composited (like TeamViewer/Remote Desktop).
    """
    raw_list = _raw_window_list()
    space_map = _get_space_index_map()
    windows: list[WindowInfo] = []

    # Virtual Desktop entry — full-screen capture
    if not app_filter:
        from hort.screen import DESKTOP_WINDOW_ID
        # Use actual main display dimensions for correct coordinate mapping
        main_display = Quartz.CGMainDisplayID()
        screen_w = Quartz.CGDisplayPixelsWide(main_display)
        screen_h = Quartz.CGDisplayPixelsHigh(main_display)
        windows.append(WindowInfo(
            window_id=DESKTOP_WINDOW_ID,
            owner_name="Desktop",
            window_name="Full Screen",
            bounds=WindowBounds(x=0, y=0, width=float(screen_w), height=float(screen_h)),
            layer=0,
            owner_pid=0,
            is_on_screen=True,
            space_index=0,
        ))

    for raw in raw_list:
        wid = int(raw.get("kCGWindowNumber", 0))
        space_idx = _get_window_space(wid, space_map)
        if space_idx == 0:
            continue  # Unknown Space — hidden/system window
        win = _parse_window(raw, space_index=space_idx)
        if win is None:
            continue
        if app_filter and app_filter.lower() not in win.owner_name.lower():
            continue
        windows.append(win)

    # Sort real windows by space/app/name, Desktop stays first
    real = [w for w in windows if w.window_id != -1]
    real.sort(key=lambda w: (w.space_index, w.owner_name.lower(), w.window_name.lower()))
    desktop = [w for w in windows if w.window_id == -1]
    return desktop + real


def get_app_names() -> list[str]:
    """Get sorted unique application names from visible windows."""
    windows = list_windows()
    names = sorted({w.owner_name for w in windows})
    return names
