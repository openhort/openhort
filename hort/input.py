"""Remote input simulation via macOS Quartz API."""

from __future__ import annotations

import subprocess

from ApplicationServices import (  # type: ignore[import-untyped]
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    AXValueGetValue,
    kAXValueTypeCGPoint,
    kAXValueTypeCGSize,
)

import Quartz  # type: ignore[import-untyped]
from AppKit import NSRunningApplication  # type: ignore[import-untyped]

from hort.models import InputEvent, WindowBounds

# Virtual keycodes for special keys (macOS)
KEYCODE_MAP: dict[str, int] = {
    "Return": 36, "Enter": 36, "Tab": 48, "Space": 49,
    "Backspace": 51, "Delete": 51, "ForwardDelete": 117,
    "Escape": 53,
    "ArrowUp": 126, "ArrowDown": 125, "ArrowLeft": 123, "ArrowRight": 124,
    "Home": 115, "End": 119, "PageUp": 116, "PageDown": 121,
    "F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97,
    "F7": 98, "F8": 100, "F9": 101, "F10": 109, "F11": 103, "F12": 111,
}

MODIFIER_FLAGS: dict[str, int] = {
    "shift": Quartz.kCGEventFlagMaskShift,
    "ctrl": Quartz.kCGEventFlagMaskControl,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "cmd": Quartz.kCGEventFlagMaskCommand,
    "meta": Quartz.kCGEventFlagMaskCommand,
}


def _to_screen_coords(
    nx: float, ny: float, bounds: WindowBounds
) -> tuple[float, float]:
    """Convert normalized (0-1) coordinates to screen coordinates."""
    return bounds.x + nx * bounds.width, bounds.y + ny * bounds.height


def _modifier_mask(modifiers: list[str]) -> int:
    """Combine modifier names into a CGEvent flag mask."""
    mask = 0
    for mod in modifiers:
        mask |= MODIFIER_FLAGS.get(mod.lower(), 0)
    return mask


def _activate_app(pid: int, bounds: WindowBounds | None = None) -> None:  # pragma: no cover
    """Bring a specific window to front, unminimize it, and switch Space.

    Strategy:
    1. AppleScript `activate` — most reliable, handles Space switching
       and unminimizing. Requires one-time Automation permission approval.
    2. AX API — raise the specific window by matching bounds.
       Handles multiple windows of the same app.
    """
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if not app:
        return

    # Step 1: AppleScript activate (switches Space, unminimizes)
    bundle_id: str | None = app.bundleIdentifier()
    name: str | None = app.localizedName()
    target = f'application id "{bundle_id}"' if bundle_id else f'application "{name}"'
    if bundle_id or name:
        try:
            subprocess.run(
                ["osascript", "-e", f"tell {target} to activate"],
                capture_output=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            # App doesn't support AppleScript — fall back to NSRunningApplication
            app.activateWithOptions_(1 << 1)

    # Step 2: AX API — raise the SPECIFIC window (by bounds matching)
    _ax_raise_window(pid, bounds)


def _ax_raise_window(pid: int, bounds: WindowBounds | None) -> None:  # pragma: no cover
    """Use Accessibility API to raise and unminimize a specific window."""
    ax_app = AXUIElementCreateApplication(pid)
    err, ax_windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
    if err != 0 or not ax_windows:
        return

    for ax_win in ax_windows:
        if bounds is not None and not _ax_bounds_match(ax_win, bounds):
            continue

        # Unminimize if needed
        err_m, minimized = AXUIElementCopyAttributeValue(
            ax_win, "AXMinimized", None
        )
        if err_m == 0 and minimized:
            AXUIElementSetAttributeValue(ax_win, "AXMinimized", False)

        AXUIElementPerformAction(ax_win, "AXRaise")

        if bounds is not None:
            break


def _ax_bounds_match(ax_win: object, bounds: WindowBounds) -> bool:  # pragma: no cover
    """Check if an AX window's position/size matches the given bounds."""
    err_p, pos_val = AXUIElementCopyAttributeValue(ax_win, "AXPosition", None)
    err_s, size_val = AXUIElementCopyAttributeValue(ax_win, "AXSize", None)
    if err_p != 0 or err_s != 0:
        return False
    _, point = AXValueGetValue(pos_val, kAXValueTypeCGPoint, None)
    _, size = AXValueGetValue(size_val, kAXValueTypeCGSize, None)
    # Tolerance of 20px — CGWindow and AX bounds can differ due to
    # window chrome, shadows, and Retina scaling
    matched: bool = (
        abs(float(point.x) - bounds.x) <= 20
        and abs(float(point.y) - bounds.y) <= 20
        and abs(float(size.width) - bounds.width) <= 20
        and abs(float(size.height) - bounds.height) <= 20
    )
    return matched


def _post_mouse(
    event_type: int,
    x: float,
    y: float,
    button: int = Quartz.kCGMouseButtonLeft,
    modifiers: int = 0,
) -> None:  # pragma: no cover
    """Post a mouse event at the given screen coordinates."""
    point = Quartz.CGPointMake(x, y)
    event = Quartz.CGEventCreateMouseEvent(None, event_type, point, button)
    if modifiers:
        Quartz.CGEventSetFlags(event, modifiers)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _post_key(keycode: int, down: bool, modifiers: int = 0) -> None:  # pragma: no cover
    """Post a keyboard event."""
    event = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
    if modifiers:
        Quartz.CGEventSetFlags(event, modifiers)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _post_key_char(char: str, modifiers: int = 0) -> None:  # pragma: no cover
    """Post a key event for a single character using unicode string."""
    event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    Quartz.CGEventKeyboardSetUnicodeString(event, len(char), char)
    if modifiers:
        Quartz.CGEventSetFlags(event, modifiers)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def _post_scroll(x: float, y: float, dx: int, dy: int) -> None:  # pragma: no cover
    """Post a scroll event at the given screen coordinates."""
    point = Quartz.CGPointMake(x, y)
    move = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, move)
    scroll = Quartz.CGEventCreateScrollWheelEvent(None, 0, 2, dy, dx)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, scroll)


def handle_input(event: InputEvent, bounds: WindowBounds, pid: int = 0) -> None:
    """Process an input event, translating normalized coords to screen coords.

    When pid > 0, the target app is activated first so it receives
    keyboard focus and mouse events.
    """
    sx, sy = _to_screen_coords(event.nx, event.ny, bounds)
    mod_mask = _modifier_mask(event.modifiers)

    if event.type in ("click", "double_click", "right_click"):
        # Bring the specific window to front so the click lands correctly
        if pid:
            _activate_app(pid, bounds=bounds)
        _post_mouse(Quartz.kCGEventMouseMoved, sx, sy)
    elif event.type == "move":
        _post_mouse(Quartz.kCGEventMouseMoved, sx, sy)

    if event.type == "click":
        _post_mouse(Quartz.kCGEventLeftMouseDown, sx, sy, modifiers=mod_mask)
        _post_mouse(Quartz.kCGEventLeftMouseUp, sx, sy, modifiers=mod_mask)

    elif event.type == "double_click":
        for _ in range(2):
            _post_mouse(Quartz.kCGEventLeftMouseDown, sx, sy, modifiers=mod_mask)
            _post_mouse(Quartz.kCGEventLeftMouseUp, sx, sy, modifiers=mod_mask)

    elif event.type == "right_click":
        _post_mouse(
            Quartz.kCGEventRightMouseDown, sx, sy,
            button=Quartz.kCGMouseButtonRight, modifiers=mod_mask,
        )
        _post_mouse(
            Quartz.kCGEventRightMouseUp, sx, sy,
            button=Quartz.kCGMouseButtonRight, modifiers=mod_mask,
        )

    elif event.type == "scroll":
        _post_scroll(sx, sy, int(event.dx), int(event.dy))

    elif event.type == "key":
        # Ensure target app has focus for key events
        if pid:
            _activate_app(pid, bounds=bounds)
        key = event.key
        if key in KEYCODE_MAP:
            keycode = KEYCODE_MAP[key]
            _post_key(keycode, True, mod_mask)
            _post_key(keycode, False, mod_mask)
        elif len(key) == 1:
            _post_key_char(key, mod_mask)
