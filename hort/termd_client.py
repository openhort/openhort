"""Client for the terminal daemon (hort-termd).

The web server uses this to communicate with the persistent terminal
daemon over a Unix socket.  Terminal sessions survive web server restarts.

If the daemon isn't running, ``ensure_daemon()`` auto-starts it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

SOCKET_PATH = Path("/tmp/hort-termd.sock")


async def _send_cmd(cmd: dict[str, Any]) -> dict[str, Any]:
    """Send a command to the daemon and return the response."""
    reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    try:
        writer.write(json.dumps(cmd).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        return json.loads(line.decode()) if line else {"ok": False, "error": "No response"}
    finally:
        writer.close()
        await writer.wait_closed()


def ensure_daemon() -> None:
    """Start the terminal daemon if it's not already running."""
    if SOCKET_PATH.exists():
        # Check if the socket is actually alive
        try:
            import socket

            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(SOCKET_PATH))
            s.close()
            return  # Daemon is alive
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            # Stale socket — remove and restart
            try:
                SOCKET_PATH.unlink()
            except OSError:
                pass

    # Start daemon as a background process
    subprocess.Popen(
        [sys.executable, "-m", "hort.termd"],
        stdout=open("/tmp/hort-termd.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    # Wait for socket to appear
    import time

    for _ in range(30):
        if SOCKET_PATH.exists():
            return
        time.sleep(0.1)
    logger.warning("hort-termd did not start within 3 seconds")


async def spawn_terminal(
    target_id: str,
    command: list[str] | None = None,
    cols: int = 120,
    rows: int = 30,
) -> dict[str, Any]:
    """Spawn a new terminal session via the daemon."""
    cmd: dict[str, Any] = {
        "cmd": "spawn",
        "target_id": target_id,
        "cols": cols,
        "rows": rows,
    }
    if command:
        cmd["command"] = command
    return await _send_cmd(cmd)


async def list_terminals() -> list[dict[str, Any]]:
    """List all terminal sessions."""
    resp = await _send_cmd({"cmd": "list"})
    result: list[dict[str, Any]] = resp.get("terminals", [])
    return result


async def close_terminal(terminal_id: str) -> bool:
    """Close a terminal session."""
    resp = await _send_cmd({"cmd": "close", "terminal_id": terminal_id})
    ok: bool = resp.get("ok", False)
    return ok


async def resize_terminal(terminal_id: str, cols: int, rows: int) -> None:
    """Resize a terminal session."""
    await _send_cmd({"cmd": "resize", "terminal_id": terminal_id, "cols": cols, "rows": rows})


async def handle_terminal_ws(
    websocket: WebSocket,
    terminal_id: str,
) -> None:
    """Bridge a browser WebSocket to a daemon terminal session.

    1. Connect to daemon, attach to the terminal
    2. Send scrollback to browser
    3. Forward daemon output → browser (binary)
    4. Forward browser input → daemon
    """
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
    except (ConnectionRefusedError, FileNotFoundError):
        await websocket.close(code=4004, reason="Terminal daemon not running")
        return

    # Attach to the terminal
    writer.write(json.dumps({"cmd": "attach", "terminal_id": terminal_id}).encode() + b"\n")
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=5)
    resp = json.loads(line.decode()) if line else {}

    if not resp.get("ok"):
        writer.close()
        await websocket.close(code=4004, reason=resp.get("error", "Attach failed"))
        return

    await websocket.accept()

    # Send scrollback
    scrollback_b64 = resp.get("scrollback", "")
    if scrollback_b64:
        await websocket.send_bytes(base64.b64decode(scrollback_b64))

    async def daemon_to_browser() -> None:
        """Read output frames from daemon and send to browser."""
        try:
            while True:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # Check for cancellation
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                    if "out" in msg:
                        await websocket.send_bytes(base64.b64decode(msg["out"]))
                except (json.JSONDecodeError, KeyError):
                    pass
        except (asyncio.CancelledError, ConnectionError):
            pass

    async def browser_to_daemon() -> None:
        """Read input from browser and send to daemon."""
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.receive":
                    if "bytes" in msg and msg["bytes"]:
                        # Send input to daemon
                        cmd = {
                            "cmd": "input",
                            "terminal_id": terminal_id,
                            "data": base64.b64encode(msg["bytes"]).decode(),
                        }
                        writer.write(json.dumps(cmd).encode() + b"\n")
                        await writer.drain()
                    elif "text" in msg and msg["text"]:
                        # Resize command
                        try:
                            data = json.loads(msg["text"])
                            if data.get("type") == "resize":
                                cmd = {
                                    "cmd": "resize",
                                    "terminal_id": terminal_id,
                                    "cols": data.get("cols", 120),
                                    "rows": data.get("rows", 30),
                                }
                                writer.write(json.dumps(cmd).encode() + b"\n")
                                await writer.drain()
                        except (json.JSONDecodeError, TypeError):
                            pass
                elif msg["type"] == "websocket.disconnect":
                    break
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    try:
        done, pending = await asyncio.wait(
            [asyncio.create_task(daemon_to_browser()), asyncio.create_task(browser_to_daemon())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        # Detach from terminal (session stays alive in daemon)
        try:
            writer.write(json.dumps({"cmd": "detach"}).encode() + b"\n")
            await writer.drain()
        except Exception:
            pass
        writer.close()
