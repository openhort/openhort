"""Native Windows window management via Win32 API.

Uses ctypes to call user32.dll and gdi32.dll directly — no extra
dependencies beyond Pillow (already required by openhort).

Win32 APIs used:
- ``EnumWindows`` / ``GetWindowTextW`` / ``GetWindowRect`` — list windows
- ``PrintWindow`` / ``BitBlt`` — capture window screenshots
- ``SendInput`` — mouse and keyboard simulation
- ``SetForegroundWindow`` — window activation
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
from typing import Any

from hort.ext.types import (
    ExtensionBase,
    PlatformProvider,
    WorkspaceInfo,
)
from hort.models import InputEvent, WindowBounds, WindowInfo

DESKTOP_WINDOW_ID = -1

# ── Win32 constants ──────────────────────────────────────────────────

SW_SHOW = 5
SW_RESTORE = 9
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
SM_CXSCREEN = 0
SM_CYSCREEN = 1
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
WHEEL_DELTA = 120
PW_RENDERFULLCONTENT = 2

# ── Win32 structures ─────────────────────────────────────────────────

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.wintypes.DWORD * 3),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("union", _INPUT_UNION)]


# Virtual key code mapping from web KeyboardEvent.key
_VK_MAP: dict[str, int] = {
    "Enter": 0x0D,
    "Backspace": 0x08,
    "Delete": 0x2E,
    "Tab": 0x09,
    "Escape": 0x1B,
    "ArrowUp": 0x26,
    "ArrowDown": 0x28,
    "ArrowLeft": 0x25,
    "ArrowRight": 0x27,
    "Home": 0x24,
    "End": 0x23,
    "PageUp": 0x21,
    "PageDown": 0x22,
    " ": 0x20,
    "Control": 0x11,
    "Shift": 0x10,
    "Alt": 0x12,
    "Meta": 0x5B,  # Windows key
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
}

_MOD_VK: dict[str, int] = {
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "meta": 0x5B,
    "cmd": 0x5B,
}


class WindowsNativeExtension(ExtensionBase, PlatformProvider):
    """Native Windows PlatformProvider — calls Win32 API via ctypes."""

    def activate(self, config: dict[str, Any]) -> None:
        pass

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_screen_size() -> tuple[int, int]:
        return user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)

    # ── WindowProvider ───────────────────────────────────────────────

    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        windows: list[WindowInfo] = []

        # Virtual Desktop entry
        if not app_filter:
            sw, sh = self._get_screen_size()
            windows.append(WindowInfo(
                window_id=DESKTOP_WINDOW_ID,
                owner_name="Desktop",
                window_name="Full Screen",
                bounds=WindowBounds(x=0, y=0, width=float(sw), height=float(sh)),
                layer=-1,
                owner_pid=0,
                is_on_screen=True,
                space_index=0,
            ))

        def enum_callback(hwnd: int, _lparam: Any) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True

            # Filter out tool windows and windows without titles
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            # Must have a caption (title bar) and not be a tool window
            if not (style & WS_CAPTION):
                return True
            if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
                return True

            # Get title
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

            if not title:
                return True

            # Get bounds
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            x, y = rect.left, rect.top
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            if w <= 0 or h <= 0:
                return True

            # Get process name
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            owner_name = _get_process_name(pid.value)

            if app_filter and app_filter.lower() not in owner_name.lower():
                return True

            windows.append(WindowInfo(
                window_id=hwnd,
                owner_name=owner_name,
                window_name=title,
                bounds=WindowBounds(x=float(x), y=float(y), width=float(w), height=float(h)),
                layer=0,
                owner_pid=pid.value,
                is_on_screen=True,
                space_index=1,
            ))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        windows.sort(key=lambda w: (w.space_index, w.owner_name.lower(), w.window_name.lower()))
        return windows

    # get_app_names() — inherited from WindowProvider base class

    # ── CaptureProvider ──────────────────────────────────────────────

    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None:

        if window_id == DESKTOP_WINDOW_ID:
            return self._capture_desktop(max_width, quality)

        return self._capture_hwnd(window_id, max_width, quality)

    def _capture_desktop(self, max_width: int, quality: int) -> bytes | None:
        """Capture the full desktop using BitBlt from the screen DC."""

        sw, sh = self._get_screen_size()
        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, sw, sh)
        gdi32.SelectObject(hdc_mem, hbmp)
        gdi32.BitBlt(hdc_mem, 0, 0, sw, sh, hdc_screen, 0, 0, SRCCOPY)

        img = _hbmp_to_pil(hdc_mem, hbmp, sw, sh)

        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

        if img is None:
            return None

        return _pil_to_jpeg(img, max_width, quality)

    def _capture_hwnd(self, hwnd: int, max_width: int, quality: int) -> bytes | None:
        """Capture a specific window using PrintWindow."""

        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None

        hdc_window = user32.GetDC(hwnd)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
        gdi32.SelectObject(hdc_mem, hbmp)

        # PrintWindow captures the window even if partially occluded
        user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)

        img = _hbmp_to_pil(hdc_mem, hbmp, w, h)

        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)

        if img is None:
            return None

        return _pil_to_jpeg(img, max_width, quality)

    # ── InputProvider ────────────────────────────────────────────────

    def handle_input(
        self, event: InputEvent, bounds: WindowBounds, pid: int = 0
    ) -> None:
        sx = int(bounds.x + event.nx * bounds.width)
        sy = int(bounds.y + event.ny * bounds.height)

        if event.type in ("click", "double_click", "right_click"):
            _move_mouse(sx, sy)
            if event.type == "click":
                _click(left=True)
            elif event.type == "double_click":
                _click(left=True)
                _click(left=True)
            elif event.type == "right_click":
                _click(left=False)

        elif event.type == "move":
            _move_mouse(sx, sy)

        elif event.type == "scroll":
            _move_mouse(sx, sy)
            delta = int(-event.dy * WHEEL_DELTA)
            _send_input_mouse(0, 0, delta, MOUSEEVENTF_WHEEL)

        elif event.type == "key":
            _send_key(event.key, event.modifiers)

    def activate_app(
        self, pid: int, bounds: WindowBounds | None = None
    ) -> None:
        if not pid:
            return
        # Find the first visible window for this PID
        target_hwnd = None

        def find_callback(hwnd: int, _lparam: Any) -> bool:
            nonlocal target_hwnd
            if not user32.IsWindowVisible(hwnd):
                return True
            win_pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
            if win_pid.value == pid:
                target_hwnd = hwnd
                return False  # stop enumeration
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(find_callback), 0)

        if target_hwnd:
            user32.ShowWindow(target_hwnd, SW_RESTORE)
            user32.SetForegroundWindow(target_hwnd)

    # ── WorkspaceProvider ────────────────────────────────────────────

    def get_workspaces(self) -> list[WorkspaceInfo]:
        # Windows virtual desktops are accessible via undocumented COM.
        # For now, report a single workspace.
        return [WorkspaceInfo(index=1, is_current=True, name="Desktop 1")]

    def switch_to(self, target_index: int) -> bool:
        # Virtual desktop switching requires undocumented COM interfaces.
        return target_index == 1


# ── Win32 helper functions ───────────────────────────────────────────


def _get_process_name(pid: int) -> str:
    """Get the executable name for a process ID."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "Unknown"
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.wintypes.DWORD(260)
        kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        # Extract just the filename without extension
        path = buf.value
        if "\\" in path:
            path = path.rsplit("\\", 1)[1]
        if "." in path:
            path = path.rsplit(".", 1)[0]
        return path or "Unknown"
    finally:
        kernel32.CloseHandle(handle)


def _hbmp_to_pil(
    hdc: int, hbmp: int, width: int, height: int
) -> "Image.Image | None":
    """Convert a Windows HBITMAP to a PIL Image."""
    from PIL import Image

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    buf_size = width * height * 4
    buf = ctypes.create_string_buffer(buf_size)

    result = gdi32.GetDIBits(hdc, hbmp, 0, height, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    if result == 0:
        return None

    # BGRA → RGBA
    img = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)
    return img.convert("RGB")


def _pil_to_jpeg(
    img: "Image.Image", max_width: int, quality: int
) -> bytes:
    """Resize if needed and encode as JPEG."""
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize(
            (max_width, int(img.height * ratio)),
            getattr(img, "Resampling", img).LANCZOS
            if hasattr(img, "Resampling")
            else 1,  # LANCZOS = 1 in older Pillow
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _move_mouse(x: int, y: int) -> None:
    """Move the mouse cursor to absolute screen coordinates."""
    user32.SetCursorPos(x, y)


def _click(left: bool = True) -> None:
    """Send a mouse click at the current cursor position."""
    if left:
        down_flag = MOUSEEVENTF_LEFTDOWN
        up_flag = MOUSEEVENTF_LEFTUP
    else:
        down_flag = MOUSEEVENTF_RIGHTDOWN
        up_flag = MOUSEEVENTF_RIGHTUP
    _send_input_mouse(0, 0, 0, down_flag)
    _send_input_mouse(0, 0, 0, up_flag)


def _send_input_mouse(dx: int, dy: int, data: int, flags: int) -> None:
    """Send a mouse input event."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = dx
    inp.union.mi.dy = dy
    inp.union.mi.mouseData = data
    inp.union.mi.dwFlags = flags
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _send_key(key: str, modifiers: list[str]) -> None:
    """Send a key press with optional modifiers."""
    # Press modifiers
    for mod in modifiers:
        vk = _MOD_VK.get(mod.lower())
        if vk:
            _send_input_key(vk=vk, flags=0)

    # Send the key
    vk = _VK_MAP.get(key)
    if vk:
        # Known special key — use virtual key code
        _send_input_key(vk=vk, flags=0)
        _send_input_key(vk=vk, flags=KEYEVENTF_KEYUP)
    elif len(key) == 1:
        # Printable character — use Unicode input
        scan = ord(key)
        _send_input_key(scan=scan, flags=KEYEVENTF_UNICODE)
        _send_input_key(scan=scan, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)

    # Release modifiers (reverse order)
    for mod in reversed(modifiers):
        vk = _MOD_VK.get(mod.lower())
        if vk:
            _send_input_key(vk=vk, flags=KEYEVENTF_KEYUP)


def _send_input_key(vk: int = 0, scan: int = 0, flags: int = 0) -> None:
    """Send a keyboard input event."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.wScan = scan
    inp.union.ki.dwFlags = flags
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
