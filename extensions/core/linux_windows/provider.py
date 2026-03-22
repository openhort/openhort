"""Linux window management via X11 tools inside a Docker container.

All window operations (list, capture, input, workspaces) run via
``docker exec`` into a container running Xvfb + a window manager.

X11 tools used:
- ``wmctrl -l -p -x`` — list windows with PID and WM_CLASS
- ``import -window <id> jpeg:-`` — capture window screenshot (ImageMagick)
- ``xdotool`` — mouse/keyboard simulation, window activation
- ``wmctrl -d`` — list virtual desktops (workspaces)
"""

from __future__ import annotations

import io
from typing import Any

from hort.ext.types import (
    ExtensionBase,
    PlatformProvider,
    WorkspaceInfo,
)
from hort.models import InputEvent, WindowBounds, WindowInfo

# X11 keyname mapping from web KeyboardEvent.key to xdotool names
_KEY_MAP: dict[str, str] = {
    "Enter": "Return",
    "Backspace": "BackSpace",
    "Delete": "Delete",
    "ArrowUp": "Up",
    "ArrowDown": "Down",
    "ArrowLeft": "Left",
    "ArrowRight": "Right",
    "Escape": "Escape",
    "Tab": "Tab",
    " ": "space",
    "Home": "Home",
    "End": "End",
    "PageUp": "Prior",
    "PageDown": "Next",
}


class LinuxWindowsExtension(ExtensionBase, PlatformProvider):
    """Linux PlatformProvider — runs X11 commands inside a Docker container."""

    def __init__(self) -> None:
        self._container_name = "openhort-linux-desktop"
        self._image = "openhort-linux-desktop"
        self._display = ":99"

    def activate(self, config: dict[str, Any]) -> None:
        self._container_name = config.get("container_name", self._container_name)
        self._image = config.get("image", self._image)

    # -- helpers --

    def _exec_sync(self, cmd: str, timeout: float = 5) -> tuple[int, str, str]:
        """Run a command in the container synchronously."""
        import subprocess

        result = subprocess.run(
            ["docker", "exec", "-e", f"DISPLAY={self._display}",
             self._container_name, "sh", "-c", cmd],
            capture_output=True, timeout=timeout,
        )
        return (
            result.returncode,
            result.stdout.decode(errors="replace"),
            result.stderr.decode(errors="replace"),
        )

    def _exec_binary(self, cmd: str) -> tuple[int, bytes]:
        """Run a command and return raw stdout bytes."""
        import subprocess

        result = subprocess.run(
            ["docker", "exec", "-e", f"DISPLAY={self._display}",
             self._container_name, "sh", "-c", cmd],
            capture_output=True, timeout=10,
        )
        return result.returncode, result.stdout

    # -- WindowProvider --

    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        rc, stdout, _ = self._exec_sync("wmctrl -l -p -x -G")
        if rc != 0:
            return []

        windows: list[WindowInfo] = []
        for line in stdout.strip().splitlines():
            win = _parse_wmctrl_line(line)
            if win is None:
                continue
            if app_filter and app_filter.lower() not in win.owner_name.lower():
                continue
            windows.append(win)

        windows.sort(key=lambda w: (w.space_index, w.owner_name.lower(), w.window_name.lower()))
        return windows

    def get_app_names(self) -> list[str]:
        return sorted({w.owner_name for w in self.list_windows()})

    # -- CaptureProvider --

    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None:
        hex_id = f"0x{window_id:08x}"
        rc, raw = self._exec_binary(
            f"import -window {hex_id} -quality {quality} jpeg:-"
        )
        if rc != 0 or len(raw) < 10:
            return None

        # Resize if needed
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize(
                (max_width, int(img.height * ratio)), Image.Resampling.LANCZOS
            )
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()

        return raw

    # -- InputProvider --

    def handle_input(
        self, event: InputEvent, bounds: WindowBounds, pid: int = 0
    ) -> None:
        sx = int(bounds.x + event.nx * bounds.width)
        sy = int(bounds.y + event.ny * bounds.height)
        t = 2  # short timeout for input commands

        if event.type == "click":
            self._exec_sync(f"xdotool mousemove {sx} {sy} click 1", timeout=t)
        elif event.type == "double_click":
            self._exec_sync(f"xdotool mousemove {sx} {sy} click --repeat 2 1", timeout=t)
        elif event.type == "right_click":
            self._exec_sync(f"xdotool mousemove {sx} {sy} click 3", timeout=t)
        elif event.type == "move":
            self._exec_sync(f"xdotool mousemove {sx} {sy}", timeout=t)
        elif event.type == "scroll":
            btn = "4" if event.dy < 0 else "5"
            clicks = max(1, abs(int(event.dy)))
            self._exec_sync(
                f"xdotool mousemove {sx} {sy} click --repeat {clicks} {btn}", timeout=t
            )
        elif event.type == "key":
            key = event.key
            # The browser resolves modifiers into e.key for printable chars:
            #   Shift+1 → "!", Shift+[ → "{", Shift+a → "A"
            # So for single printable chars, use xdotool type (shift is
            # already baked into the character). Only use xdotool key when
            # ctrl/alt/cmd are involved or for special keys (Enter, Tab...).
            non_shift_mods = [m for m in event.modifiers if m.lower() != "shift"]
            is_printable = len(key) == 1 and key not in _KEY_MAP
            if is_printable and not non_shift_mods:
                self._exec_sync(
                    f"xdotool type --clearmodifiers -- {_shell_quote(key)}", timeout=t
                )
            else:
                xkey = _KEY_MAP.get(key, key)
                all_mods = "+".join(event.modifiers) + "+" if event.modifiers else ""
                self._exec_sync(f"xdotool key {all_mods}{xkey}", timeout=t)

    def activate_app(
        self, pid: int, bounds: WindowBounds | None = None
    ) -> None:
        if pid:
            self._exec_sync(f"wmctrl -i -a $(wmctrl -l -p | awk '$3=={pid}{{print $1; exit}}')")

    # -- WorkspaceProvider --

    def get_workspaces(self) -> list[WorkspaceInfo]:
        rc, stdout, _ = self._exec_sync("wmctrl -d")
        if rc != 0:
            return [WorkspaceInfo(index=1, is_current=True)]

        workspaces: list[WorkspaceInfo] = []
        for i, line in enumerate(stdout.strip().splitlines()):
            parts = line.split()
            is_current = len(parts) > 1 and parts[1] == "*"
            name = parts[-1] if len(parts) > 1 else f"Desktop {i + 1}"
            workspaces.append(WorkspaceInfo(
                index=i + 1, is_current=is_current, name=name
            ))
        return workspaces or [WorkspaceInfo(index=1, is_current=True)]

    def switch_to(self, target_index: int) -> bool:
        rc, _, _ = self._exec_sync(f"wmctrl -s {target_index - 1}")
        return rc == 0


def _shell_quote(s: str) -> str:
    """Shell-quote a string safely for use in docker exec sh -c."""
    import shlex

    return shlex.quote(s)


def _parse_wmctrl_line(line: str) -> WindowInfo | None:
    """Parse a line from ``wmctrl -l -p -x -G`` into a WindowInfo.

    Format: ``0x01200003  0  1234  50  100  800  600  xterm.XTerm  hostname  Title``
    Fields: wid desktop pid x y w h wm_class hostname title...
    """
    parts = line.split(None, 9)
    if len(parts) < 9:
        return None

    try:
        wid = int(parts[0], 16)
    except ValueError:
        return None

    desktop = int(parts[1]) if parts[1].lstrip("-").isdigit() else 0
    pid = int(parts[2]) if parts[2].isdigit() else 0

    try:
        x, y, w, h = float(parts[3]), float(parts[4]), float(parts[5]), float(parts[6])
    except ValueError:
        x, y, w, h = 0, 0, 800, 600

    if w <= 0 or h <= 0:
        return None

    wm_class = parts[7]
    # owner_name = second part of WM_CLASS (e.g. "xterm.XTerm" → "XTerm")
    class_parts = wm_class.split(".")
    owner_name = class_parts[-1] if class_parts else wm_class

    # Window title: parts[8] is hostname, parts[9] is title (if present)
    window_name = parts[9].strip() if len(parts) > 9 else ""

    if not window_name:
        return None

    bounds = WindowBounds(x=x, y=y, width=w, height=h)

    return WindowInfo(
        window_id=wid,
        owner_name=owner_name,
        window_name=window_name,
        bounds=bounds,
        layer=0,
        owner_pid=pid,
        is_on_screen=True,
        space_index=max(1, desktop + 1),  # wmctrl is 0-based, we're 1-based
    )
