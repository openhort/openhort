"""LlmingLens — remote desktop viewer extension with MCP tools.

Provides screen streaming, window browsing, and input control as a proper
extension. Appears as a single card on the main grid with a live desktop
thumbnail preview. Click to enter the viewer submenu.

MCP tools (served via ``python -m hort.mcp_server``):
- ``list_windows`` — list visible windows with optional app filter
- ``get_window_info`` — detailed OS metadata for all matching windows
- ``screenshot`` — unified desktop/window capture with crop, zoom, grid overlay
- ``click`` — click at screen/window coordinates
- ``type_text`` — type text string
- ``press_key`` — press a special key (Return, Escape, arrow keys, etc.)

Connector commands (Telegram, etc.):
- ``/windows`` — list visible windows
- ``/screenshot [target]`` — capture desktop or a window, returns image
"""

from __future__ import annotations

import base64
import fnmatch
import logging
import re
import time
from typing import Any

from hort.ext.connectors import (
    ConnectorCapabilities,
    ConnectorCommand,
    ConnectorResponse,
    IncomingMessage,
)
from hort.llming import LlmingBase, Power, PowerType

logger = logging.getLogger(__name__)


def _match_filter(name: str, pattern: str) -> bool:
    """Match a window/app name against a filter pattern.

    Supports:
    - Exact match (case-insensitive)
    - Glob patterns: ``*Chrome*``, ``Fire*``
    - Regex (prefix with ``/``): ``/^Google.*/i``
    """
    if not pattern:
        return True
    # Regex pattern
    if pattern.startswith("/"):
        parts = pattern[1:].rsplit("/", 1)
        regex = parts[0]
        flags = re.IGNORECASE if len(parts) > 1 and "i" in parts[1] else 0
        return bool(re.search(regex, name, flags))
    # Glob pattern (case-insensitive)
    return fnmatch.fnmatch(name.lower(), pattern.lower())


def _matches_any(name: str, patterns: list[str]) -> bool:
    """Check if name matches any of the comma-separated patterns."""
    return any(_match_filter(name, p.strip()) for p in patterns)


def _filter_windows(windows: list[Any], app_filter: str | None) -> list[Any]:
    """Filter windows by app_filter patterns (comma-separated)."""
    if not app_filter:
        return windows
    patterns = [p.strip() for p in app_filter.split(",") if p.strip()]
    if not patterns:
        return windows
    return [w for w in windows if _matches_any(w.owner_name, patterns)]


def _annotate_grid(pil_image: Any, grid_cols: int = 4, grid_rows: int = 4) -> Any:
    """Draw a labeled grid overlay on a PIL image for spatial navigation.

    Returns the annotated image. Each cell is labeled A1..D4 (cols=A-Z, rows=1-N).
    """
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(pil_image, "RGBA")
    w, h = pil_image.size

    cell_w = w / grid_cols
    cell_h = h / grid_rows

    # Semi-transparent colored cells (alternating)
    colors = [
        (59, 130, 246, 30),   # blue
        (239, 68, 68, 30),    # red
        (34, 197, 94, 30),    # green
        (168, 85, 247, 30),   # purple
    ]

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", size=max(14, min(cell_w, cell_h) // 5))
    except Exception:
        font = ImageFont.load_default()

    for row in range(grid_rows):
        for col in range(grid_cols):
            x1 = int(col * cell_w)
            y1 = int(row * cell_h)
            x2 = int((col + 1) * cell_w)
            y2 = int((row + 1) * cell_h)

            # Alternating cell background
            color_idx = (row + col) % len(colors)
            draw.rectangle([x1, y1, x2, y2], fill=colors[color_idx])

            # Grid lines
            draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 255, 100), width=1)

            # Cell label (e.g. A1, B3)
            label = f"{chr(65 + col)}{row + 1}"
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = x1 + (cell_w - tw) / 2
            ty = y1 + (cell_h - th) / 2
            # Label background
            draw.rectangle(
                [int(tx) - 2, int(ty) - 2, int(tx) + tw + 2, int(ty) + th + 2],
                fill=(0, 0, 0, 180),
            )
            draw.text((int(tx), int(ty)), label, fill=(255, 255, 255, 230), font=font)

    return pil_image


def _user_recently_active(threshold: float = 2.0) -> bool:
    """Check if the user has interacted (mouse/keyboard) recently.

    Uses macOS CGEventSource to detect last user input. Returns True
    if user input was within ``threshold`` seconds.
    """
    try:
        import Quartz  # type: ignore[import-untyped]
        # Check combined session state for any HID events
        for event_type in (
            Quartz.kCGEventLeftMouseDown,
            Quartz.kCGEventRightMouseDown,
            Quartz.kCGEventKeyDown,
            Quartz.kCGEventMouseMoved,
        ):
            elapsed = Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateCombinedSessionState, event_type
            )
            if elapsed < threshold:
                return True
    except Exception:
        pass
    return False


# ── Tool definitions ──────────────────────────────────────────────────

TOOLS = [
    Power(
        name="list_windows",
        type=PowerType.MCP,
        description=(
            "List visible windows on the desktop. Returns window names, IDs, "
            "app names, and which desktop Space they're on. Use app_filter to "
            "restrict results to specific apps (supports glob patterns and regex)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "app_filter": {
                    "type": "string",
                    "description": (
                        "Comma-separated app name patterns. Supports glob "
                        "(e.g. 'Chrome*,Firefox') or regex (e.g. '/^Google.*/i'). "
                        "Empty = all apps."
                    ),
                },
            },
        },
    ),
    Power(
        name="get_window_info",
        type=PowerType.MCP,
        description=(
            "Get detailed OS-level metadata for all visible windows: bounds "
            "(x, y, width, height), desktop Space index, owner PID, on-screen "
            "status. Use app_filter to restrict results."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "app_filter": {
                    "type": "string",
                    "description": "Comma-separated app name patterns (glob/regex).",
                },
            },
        },
    ),
    Power(
        name="screenshot",
        type=PowerType.MCP,
        description=(
            "Capture a screenshot of the desktop or a specific window. "
            "For ultrawide/high-res displays, ALWAYS use grid=true first to see "
            "the overview with labeled cells (A1-D4), then grid_cell='B2' to zoom "
            "into the area you need to read. Direct full-screen captures are too "
            "small to read text on large displays. "
            "Returns a base64-encoded WebP image with coordinate metadata."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "What to capture: 'desktop' for full screen, or a "
                        "window_id (integer as string). Default: 'desktop'."
                    ),
                    "default": "desktop",
                },
                "region": {
                    "type": "object",
                    "description": (
                        "Crop region in normalized coordinates (0.0-1.0). "
                        "Omit for full capture."
                    ),
                    "properties": {
                        "x": {"type": "number", "description": "Left edge (0.0-1.0)"},
                        "y": {"type": "number", "description": "Top edge (0.0-1.0)"},
                        "w": {"type": "number", "description": "Width (0.0-1.0)"},
                        "h": {"type": "number", "description": "Height (0.0-1.0)"},
                    },
                    "required": ["x", "y", "w", "h"],
                },
                "grid_cell": {
                    "type": "string",
                    "description": (
                        "Zoom into a grid cell from a previous grid screenshot "
                        "(e.g. 'B2'). Automatically sets the region. "
                        "Grid uses 4x4 layout: columns A-D, rows 1-4."
                    ),
                },
                "grid": {
                    "type": "boolean",
                    "description": (
                        "Overlay a 4x4 labeled grid (A1-D4) on the screenshot "
                        "for spatial navigation. Use grid_cell to zoom into a "
                        "cell on the next call."
                    ),
                    "default": False,
                },
                "max_width": {
                    "type": "integer",
                    "description": "Maximum image width in pixels. Default: 1920. Use higher for zoomed crops.",
                    "default": 1920,
                },
                "quality": {
                    "type": "integer",
                    "description": "WebP quality (1-100). Default: 90.",
                    "default": 90,
                },
            },
        },
    ),
    Power(
        name="click",
        type=PowerType.MCP,
        description=(
            "Click at a position on the desktop or in a window. Coordinates "
            "are normalized (0.0-1.0) relative to the target bounds. "
            "The target app is activated before clicking."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Window ID or 'desktop'. Default: 'desktop'.",
                    "default": "desktop",
                },
                "x": {
                    "type": "number",
                    "description": "Horizontal position (0.0=left, 1.0=right).",
                },
                "y": {
                    "type": "number",
                    "description": "Vertical position (0.0=top, 1.0=bottom).",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "double"],
                    "description": "Mouse button. Default: 'left'.",
                    "default": "left",
                },
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["shift", "ctrl", "alt", "cmd"]},
                    "description": "Modifier keys to hold.",
                },
            },
            "required": ["x", "y"],
        },
    ),
    Power(
        name="type_text",
        type=PowerType.MCP,
        description=(
            "Type a text string using keyboard events. The target app must "
            "be focused (use click first to focus a text field)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to type.",
                },
            },
            "required": ["text"],
        },
    ),
    Power(
        name="press_key",
        type=PowerType.MCP,
        description=(
            "Press a special key (Return, Escape, Tab, arrow keys, F1-F12, etc.) "
            "with optional modifier keys."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Key name: Return, Tab, Escape, Space, Backspace, Delete, "
                        "ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Home, End, "
                        "PageUp, PageDown, F1-F12, or a single character."
                    ),
                },
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["shift", "ctrl", "alt", "cmd"]},
                    "description": "Modifier keys to hold.",
                },
            },
            "required": ["key"],
        },
    ),
]


CONNECTOR_COMMANDS = [
    ConnectorCommand(
        name="windows",
        description="List visible windows",
        plugin_id="llming-lens",
    ),
    ConnectorCommand(
        name="screenshot",
        description="Screenshot desktop or window: /screenshot [app_name|window_id]",
        plugin_id="llming-lens",
        accept_images=False,
    ),
]


class LlmingLens(LlmingBase):
    """Remote desktop viewer extension with MCP tools and connector commands."""

    _preview: dict[str, Any] = {}
    _app_filter: str | None = None
    _last_grid_region: dict[str, float] | None = None

    def activate(self, config: dict[str, Any]) -> None:
        self._preview = {}
        self._app_filter = config.get("app_filter")
        self._last_grid_region = None
        self.log.info("LlmingLens activated (app_filter=%s)", self._app_filter)

    def deactivate(self) -> None:
        self.log.info("LlmingLens deactivated")

    def get_pulse(self) -> dict[str, Any]:
        """Return desktop preview for the grid card thumbnail."""
        return self._preview

    def capture_preview(self) -> None:
        """Scheduled job: capture desktop + top 3 window thumbnails."""
        try:
            from hort.targets import TargetRegistry

            registry = TargetRegistry.get()
            provider = registry.get_default()
            if not provider:
                return

            from hort.screen import DESKTOP_WINDOW_ID

            frame = provider.capture_window(DESKTOP_WINDOW_ID, 960, 60)
            desktop_b64 = base64.b64encode(frame).decode() if frame else ""

            window_thumbs = []
            try:
                windows = provider.list_windows()
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

    # ── Powers ────────────────────────────────────────────────────────

    def get_powers(self) -> list[Power]:
        powers: list[Power] = list(TOOLS)
        # Slash commands
        for c in CONNECTOR_COMMANDS:
            powers.append(Power(
                name=c.name,
                type=PowerType.COMMAND,
                description=c.description,
            ))
        return powers

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        # MCP tools
        mcp_tools = {
            "list_windows": self._tool_list_windows,
            "get_window_info": self._tool_get_window_info,
            "screenshot": self._tool_screenshot,
            "click": self._tool_click,
            "type_text": self._tool_type_text,
            "press_key": self._tool_press_key,
        }
        if name in mcp_tools:
            try:
                return mcp_tools[name](args)
            except Exception as exc:
                self.log.exception("MCP tool %s failed", name)
                return {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "is_error": True,
                }

        # Slash commands
        message = args.get("_message")
        capabilities = args.get("_capabilities")
        if name == "windows" and message and capabilities:
            return self._cmd_windows(message, capabilities)
        if name == "screenshot" and message and capabilities:
            return self._cmd_screenshot(message, capabilities)
        if name == "_callback" and message and capabilities:
            return self._handle_callback(message, capabilities)

        return None

    def _get_effective_filter(self, args: dict[str, Any]) -> str | None:
        """Get the app filter — per-call override or configured default."""
        return args.get("app_filter") or self._app_filter

    def _get_windows(self, app_filter: str | None = None) -> list[Any]:
        """List windows with filtering."""
        from hort.windows import list_windows
        windows = list_windows()
        return _filter_windows(windows, app_filter)

    def _resolve_target(self, target: str) -> tuple[int, Any]:
        """Resolve target string to (window_id, window_info_or_none)."""
        from hort.screen import DESKTOP_WINDOW_ID
        if not target or target.lower() == "desktop":
            return DESKTOP_WINDOW_ID, None
        try:
            wid = int(target)
        except ValueError:
            # Try matching by app/window name
            windows = self._get_windows()
            for w in windows:
                if target.lower() in w.owner_name.lower() or target.lower() in w.window_name.lower():
                    return w.window_id, w
            return DESKTOP_WINDOW_ID, None
        # Find the window info for bounds
        windows = self._get_windows()
        for w in windows:
            if w.window_id == wid:
                return wid, w
        return wid, None

    def _grid_cell_to_region(self, cell: str) -> dict[str, float]:
        """Convert grid cell label (e.g. 'B2') to normalized crop region."""
        cell = cell.strip().upper()
        if len(cell) < 2:
            raise ValueError(f"Invalid grid cell: {cell}")
        col = ord(cell[0]) - ord("A")
        row = int(cell[1:]) - 1
        grid_cols, grid_rows = 4, 4
        if col < 0 or col >= grid_cols or row < 0 or row >= grid_rows:
            raise ValueError(f"Grid cell {cell} out of range (A1-D4)")
        return {
            "x": col / grid_cols,
            "y": row / grid_rows,
            "w": 1.0 / grid_cols,
            "h": 1.0 / grid_rows,
        }

    # ── Tool implementations ──────────────────────────────────────────

    def _tool_list_windows(self, args: dict[str, Any]) -> dict[str, Any]:
        app_filter = self._get_effective_filter(args)
        windows = self._get_windows(app_filter)

        lines = []
        for w in windows:
            space = f" [Space {w.space_index}]" if w.space_index else ""
            lines.append(f"  {w.window_id}: {w.owner_name} — {w.window_name}{space}")

        text = f"Windows ({len(windows)}):\n" + "\n".join(lines) if lines else "No windows found."
        return {"content": [{"type": "text", "text": text}]}

    def _tool_get_window_info(self, args: dict[str, Any]) -> dict[str, Any]:
        app_filter = self._get_effective_filter(args)
        windows = self._get_windows(app_filter)

        info_list = []
        for w in windows:
            info_list.append({
                "window_id": w.window_id,
                "owner_name": w.owner_name,
                "window_name": w.window_name,
                "bounds": {
                    "x": w.bounds.x,
                    "y": w.bounds.y,
                    "width": w.bounds.width,
                    "height": w.bounds.height,
                },
                "space_index": w.space_index,
                "owner_pid": w.owner_pid,
                "is_on_screen": w.is_on_screen,
            })

        import json
        text = json.dumps(info_list, indent=2)
        return {"content": [{"type": "text", "text": text}]}

    def _tool_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        from hort.screen import (
            DESKTOP_WINDOW_ID,
            _cgimage_crop,
            _cgimage_to_pil,
            _raw_capture,
            _raw_capture_desktop,
        )

        target = args.get("target", "desktop")
        max_width = args.get("max_width", 1920)
        quality = args.get("quality", 90)
        grid = args.get("grid", False)
        grid_cell = args.get("grid_cell")
        region = args.get("region")

        # Resolve target
        window_id, win_info = self._resolve_target(target)

        # Handle grid_cell zoom (compute region from previous grid)
        if grid_cell:
            cell_region = self._grid_cell_to_region(grid_cell)
            if self._last_grid_region:
                # Compose: zoom within the previous region
                prev = self._last_grid_region
                region = {
                    "x": prev["x"] + cell_region["x"] * prev["w"],
                    "y": prev["y"] + cell_region["y"] * prev["h"],
                    "w": cell_region["w"] * prev["w"],
                    "h": cell_region["h"] * prev["h"],
                }
            else:
                region = cell_region

        # Capture raw CGImage inside autorelease pool to prevent
        # native memory leaks on background threads.
        import objc  # type: ignore[import-untyped]

        with objc.autorelease_pool():
            if window_id == DESKTOP_WINDOW_ID:
                cg_image = _raw_capture_desktop()
            else:
                cg_image = _raw_capture(window_id)

            if cg_image is None:
                return {
                    "content": [{"type": "text", "text": f"Failed to capture {target}"}],
                    "is_error": True,
                }

            try:
                import Quartz  # type: ignore[import-untyped]
                img_w = Quartz.CGImageGetWidth(cg_image)
                img_h = Quartz.CGImageGetHeight(cg_image)

                # Apply crop region
                if region:
                    rx, ry = region["x"], region["y"]
                    rw, rh = region["w"], region["h"]
                    cropped = _cgimage_crop(cg_image, rx, ry, rw, rh)
                    del cg_image
                    cg_image = cropped
                    crop_info = {"x": rx, "y": ry, "w": rw, "h": rh}
                else:
                    crop_info = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

                # Convert to PIL
                pil_image = _cgimage_to_pil(cg_image)
            finally:
                del cg_image

        if pil_image is None:
            return {
                "content": [{"type": "text", "text": "Failed to convert image"}],
                "is_error": True,
            }

        # Apply grid overlay
        if grid:
            pil_image = _annotate_grid(pil_image)
            self._last_grid_region = crop_info
        else:
            self._last_grid_region = None

        # Resize and encode
        from hort.screen import _encode_pil_to_jpeg
        jpeg_bytes = _encode_pil_to_jpeg(pil_image, max_width, quality)

        # Build coordinate metadata
        bounds_info: dict[str, Any] = {}
        if win_info:
            bounds_info = {
                "window_bounds": {
                    "x": win_info.bounds.x,
                    "y": win_info.bounds.y,
                    "width": win_info.bounds.width,
                    "height": win_info.bounds.height,
                },
            }

        import json
        coord_text = json.dumps({
            "target": target,
            "window_id": window_id,
            "original_size": {"width": img_w, "height": img_h},
            "crop_region": crop_info,
            "grid": grid,
            "grid_layout": "4x4 (A-D columns, 1-4 rows)" if grid else None,
            **bounds_info,
        })

        return {"content": [
            {"type": "text", "text": coord_text},
            {"type": "image", "data": base64.b64encode(jpeg_bytes).decode(), "mimeType": "image/webp"},
        ]}

    def _tool_click(self, args: dict[str, Any]) -> dict[str, Any]:
        # Check user activity
        if _user_recently_active(1.5):
            return {
                "content": [{"type": "text", "text": (
                    "User input detected — automation paused. "
                    "Wait for user to finish interacting."
                )}],
                "is_error": True,
            }

        target = args.get("target", "desktop")
        nx = float(args.get("x", 0.5))
        ny = float(args.get("y", 0.5))
        button = args.get("button", "left")
        modifiers = args.get("modifiers", [])

        window_id, win_info = self._resolve_target(target)

        from hort.models import InputEvent, WindowBounds
        from hort.screen import DESKTOP_WINDOW_ID

        if window_id == DESKTOP_WINDOW_ID:
            # Desktop click: use full screen bounds
            import Quartz  # type: ignore[import-untyped]
            main_display = Quartz.CGMainDisplayID()
            bounds = WindowBounds(
                x=0, y=0,
                width=float(Quartz.CGDisplayPixelsWide(main_display)),
                height=float(Quartz.CGDisplayPixelsHigh(main_display)),
            )
            pid = 0
        elif win_info:
            bounds = win_info.bounds
            pid = win_info.owner_pid
        else:
            return {
                "content": [{"type": "text", "text": f"Window {target} not found"}],
                "is_error": True,
            }

        event_type = {"left": "click", "right": "right_click", "double": "double_click"}.get(button, "click")
        event = InputEvent(type=event_type, nx=nx, ny=ny, modifiers=modifiers)

        from hort.input import handle_input
        handle_input(event, bounds, pid)

        return {"content": [{"type": "text", "text": (
            f"Clicked at ({nx:.2f}, {ny:.2f}) on {target}"
        )}]}

    def _tool_type_text(self, args: dict[str, Any]) -> dict[str, Any]:
        if _user_recently_active(1.5):
            return {
                "content": [{"type": "text", "text": "User input detected — automation paused."}],
                "is_error": True,
            }

        text = args.get("text", "")
        if not text:
            return {
                "content": [{"type": "text", "text": "No text provided"}],
                "is_error": True,
            }

        from hort.input import _post_key_char
        for char in text:
            _post_key_char(char)
            time.sleep(0.02)  # Small delay between keystrokes

        return {"content": [{"type": "text", "text": f"Typed {len(text)} characters"}]}

    def _tool_press_key(self, args: dict[str, Any]) -> dict[str, Any]:
        if _user_recently_active(1.5):
            return {
                "content": [{"type": "text", "text": "User input detected — automation paused."}],
                "is_error": True,
            }

        key = args.get("key", "")
        modifiers = args.get("modifiers", [])

        if not key:
            return {
                "content": [{"type": "text", "text": "No key provided"}],
                "is_error": True,
            }

        from hort.input import KEYCODE_MAP, _modifier_mask, _post_key, _post_key_char

        mod_mask = _modifier_mask(modifiers)

        if key in KEYCODE_MAP:
            keycode = KEYCODE_MAP[key]
            _post_key(keycode, True, mod_mask)
            _post_key(keycode, False, mod_mask)
        elif len(key) == 1:
            _post_key_char(key, mod_mask)
        else:
            return {
                "content": [{"type": "text", "text": f"Unknown key: {key}"}],
                "is_error": True,
            }

        mod_str = "+".join(modifiers) + "+" if modifiers else ""
        return {"content": [{"type": "text", "text": f"Pressed {mod_str}{key}"}]}

    # ── Compat: pass full message/capabilities to execute_power ──

    async def handle_connector_command(
        self,
        command: str,
        message: IncomingMessage,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorResponse | None:
        """Override compat bridge to pass message and capabilities."""
        cmd_args = getattr(message, "command_args", "") or ""
        result = await self.execute_power(command, {
            "args": cmd_args,
            "_message": message,
            "_capabilities": capabilities,
        })
        if result is None:
            return None
        if isinstance(result, ConnectorResponse):
            return result
        if isinstance(result, str):
            return ConnectorResponse.simple(result)
        return result

    def _handle_callback(
        self, message: IncomingMessage, capabilities: ConnectorCapabilities
    ) -> ConnectorResponse | None:
        """Handle inline button callbacks from /windows."""
        data = message.callback_data or ""
        if not data.startswith("llming-lens:"):
            return None
        payload = data.split(":", 1)[1]
        # Fake an IncomingMessage with the window ID as command args
        from dataclasses import replace
        fake_msg = replace(message, text=f"/screenshot {payload}", callback_data=None)
        return self._cmd_screenshot(fake_msg, capabilities)

    def _cmd_windows(
        self, message: IncomingMessage, capabilities: ConnectorCapabilities
    ) -> ConnectorResponse:
        """List visible windows with clickable screenshot buttons."""
        from hort.ext.connectors import ResponseButton
        from hort.windows import list_windows

        app_filter = message.command_args.strip() or None
        windows = list_windows(app_filter=app_filter)

        if not windows:
            return ConnectorResponse.simple("No windows found.")

        text_lines = [f"Windows ({len(windows)}):"]
        html_lines = [f"<b>Windows ({len(windows)}):</b>"]
        # Build button rows (one per window, max 20)
        button_rows: list[list[ResponseButton]] = []
        for w in windows[:20]:
            space = f" [S{w.space_index}]" if w.space_index else ""
            label = f"{w.owner_name} — {w.window_name}"
            if len(label) > 40:
                label = label[:37] + "..."
            text_lines.append(f"  {w.window_id}: {w.owner_name} — {w.window_name}{space}")
            html_lines.append(
                f"  <code>{w.window_id}</code>: <b>{w.owner_name}</b> — {w.window_name}{space}"
            )
            button_rows.append([
                ResponseButton(label=label, callback_data=f"llming-lens:{w.window_id}"),
            ])

        return ConnectorResponse(
            text="\n".join(text_lines),
            html="\n".join(html_lines),
            buttons=button_rows if capabilities.inline_buttons else None,
        )

    def _cmd_screenshot(
        self, message: IncomingMessage, capabilities: ConnectorCapabilities
    ) -> ConnectorResponse:
        """Capture desktop or window screenshot. Usage: /screenshot [target]"""
        from hort.screen import DESKTOP_WINDOW_ID, capture_window
        from hort.windows import list_windows

        target_str = message.command_args.strip()

        if not target_str or target_str.lower() == "desktop":
            # Desktop screenshot
            jpeg = capture_window(DESKTOP_WINDOW_ID, max_width=1920, quality=75)
            caption = "Desktop"
        else:
            # Try as window ID first
            window_id = None
            window_name = ""
            try:
                window_id = int(target_str)
            except ValueError:
                # Search by app/window name
                windows = list_windows()
                for w in windows:
                    if (
                        target_str.lower() in w.owner_name.lower()
                        or target_str.lower() in w.window_name.lower()
                    ):
                        window_id = w.window_id
                        window_name = f"{w.owner_name} — {w.window_name}"
                        break

            if window_id is None:
                return ConnectorResponse.simple(
                    f"Window not found: {target_str}\nUse /windows to see available windows."
                )

            jpeg = capture_window(window_id, max_width=1920, quality=75)
            caption = window_name or f"Window {window_id}"

        if jpeg is None:
            return ConnectorResponse.simple("Failed to capture screenshot.")

        if capabilities.images:
            return ConnectorResponse(image=jpeg, image_caption=caption)
        else:
            # Fallback: base64 for connectors without image support
            return ConnectorResponse.simple(f"Screenshot captured ({len(jpeg)} bytes) — images not supported on this connector.")
