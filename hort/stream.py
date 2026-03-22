"""Binary WebSocket stream transport for window capture frames.

This module manages the dedicated binary WebSocket that sends JPEG frames
to the client. It reads ``stream_config`` from the session entry (set by
the control WebSocket) and captures frames in a loop.

The stream uses the active target's ``PlatformProvider`` for capture,
so it works with any platform (macOS, Linux container, remote VM).

The stream transport is separate from the control channel:
- Control WS (JSON, llming-com managed): commands, config, input events
- Stream WS (binary, this module): JPEG frames only
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket, WebSocketDisconnect

from hort.ext.types import PlatformProvider
from hort.targets import TargetRegistry

if TYPE_CHECKING:
    from hort.session import HortRegistry, HortSessionEntry

logger = logging.getLogger(__name__)


def _effective_max_width(screen_width: int, screen_dpr: float, max_width: int) -> int:
    """Cap max_width to the client's usable screen resolution."""
    if screen_width > 0 and screen_dpr > 0:
        client_pixels = int(screen_width * screen_dpr)
        return min(max_width, client_pixels)
    return max_width


def _get_provider(target_id: str = "") -> PlatformProvider | None:
    """Get a target's platform provider by ID, or the default."""
    registry = TargetRegistry.get()
    if target_id:
        return registry.get_provider(target_id)
    return registry.get_default()


async def run_stream(
    websocket: WebSocket,
    session_id: str,
    registry: HortRegistry,
) -> None:
    """Run the binary stream WebSocket for a session.

    Lifecycle:
    1. Look up session in registry
    2. Accept the connection, store as ``entry.stream_ws``
    3. Wait for ``entry.stream_config`` to be set (by the control WS)
    4. Capture loop: capture frame → send binary → sleep for 1/fps
    5. On disconnect: clear ``entry.stream_ws``
    """
    entry = registry.get_session(session_id)
    if not entry:
        await websocket.close(code=4004, reason="Session not found")
        return

    # Close existing stream WS for this session
    if entry.stream_ws is not None:
        try:
            await entry.stream_ws.close(code=4001, reason="Superseded")
        except Exception:
            pass

    await websocket.accept()
    entry.stream_ws = websocket
    entry.observer_id = registry.next_observer_id()

    prev_window_id: int = 0
    frame_count = 0
    import time as _time

    try:
        while True:
            config = entry.stream_config
            if config is None:
                await asyncio.sleep(0.1)
                continue

            provider = _get_provider(entry.active_target_id)
            if provider is None:
                logger.warning("No provider for target %s", entry.active_target_id)
                await asyncio.sleep(1.0)
                continue

            # Raise window when it changes (blocking — can take 1-2s with osascript)
            if config.window_id != prev_window_id:
                logger.info("Switching to window %d (target=%s)", config.window_id, entry.active_target_id)
                _raise_window(config.window_id, provider)
                prev_window_id = config.window_id

            effective_width = _effective_max_width(
                config.screen_width, config.screen_dpr, config.max_width
            )

            # Capture (synchronous — typically < 50ms for local, acceptable for stream FPS)
            t0 = _time.monotonic()
            frame = provider.capture_window(
                config.window_id, effective_width, config.quality
            )
            capture_ms = (_time.monotonic() - t0) * 1000

            # Log performance every 100 frames
            frame_count += 1
            if frame_count % 100 == 0:
                logger.info("Stream: %d frames, last capture %.0fms, window=%d", frame_count, capture_ms, config.window_id)

            if capture_ms > 500:
                logger.warning("Slow capture: %.0fms for window %d", capture_ms, config.window_id)

            if frame is None:
                logger.warning("Capture failed for window %d", config.window_id)
                if entry.websocket is not None:
                    try:
                        await entry.websocket.send_text(
                            json.dumps({"type": "stream_error", "error": "Window not found"})
                        )
                    except Exception:
                        pass
                await asyncio.sleep(1.0)
                entry.stream_config = None
                prev_window_id = 0
                continue

            await websocket.send_bytes(frame)
            await asyncio.sleep(1.0 / config.fps)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("Stream error for session %s: %s", session_id[:8], e)
    finally:
        entry.stream_ws = None
        entry.observer_id = 0


def _raise_window(window_id: int, provider: PlatformProvider) -> None:
    """Bring a window to front using the active provider."""
    import time as _t

    t0 = _t.monotonic()
    windows = provider.list_windows()
    list_ms = (_t.monotonic() - t0) * 1000
    win = next((w for w in windows if w.window_id == window_id), None)
    if not win or not win.owner_pid:
        logger.warning("_raise_window: window %d not found (list took %.0fms)", window_id, list_ms)
        return
    t1 = _t.monotonic()
    provider.activate_app(win.owner_pid, bounds=win.bounds)
    activate_ms = (_t.monotonic() - t1) * 1000
    logger.info("_raise_window: %s/%s pid=%d list=%.0fms activate=%.0fms",
                win.owner_name, win.window_name[:30], win.owner_pid, list_ms, activate_ms)
