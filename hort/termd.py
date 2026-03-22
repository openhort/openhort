"""Terminal daemon — persistent process that holds PTY sessions.

Runs as a separate process from the web server. Communicates via a Unix
domain socket. Terminal sessions survive web server restarts (uvicorn
--reload) because they live in this daemon's process space.

Architecture (like tmux):
- ``hort-termd`` holds all PTY sessions and their scrollback buffers
- The web server connects as a client over a Unix socket
- Multiple web server instances can connect to the same daemon
- ``hort-termd`` auto-starts when the web server needs it

Protocol (over Unix socket, newline-delimited JSON):
- Request:  ``{"cmd": "spawn", "target_id": "...", "command": [...], "cols": N, "rows": N}``
- Response: ``{"ok": true, "terminal_id": "...", "title": "..."}``
- Request:  ``{"cmd": "list"}``
- Response: ``{"ok": true, "terminals": [...]}``
- Request:  ``{"cmd": "close", "terminal_id": "..."}``
- Response: ``{"ok": true}``
- Request:  ``{"cmd": "resize", "terminal_id": "...", "cols": N, "rows": N}``
- Response: ``{"ok": true}``
- Request:  ``{"cmd": "attach", "terminal_id": "..."}``
- Response: ``{"ok": true, "scrollback": "<base64>"}``
  Then: binary PTY output frames forwarded until detach
- Request:  ``{"cmd": "input", "terminal_id": "...", "data": "<base64>"}``
- Response: (none — fire and forget)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from hort.terminal import TerminalManager, TerminalSession, _default_command

logger = logging.getLogger(__name__)

SOCKET_PATH = Path("/tmp/hort-termd.sock")
PROTOCOL_VERSION = 1


class DaemonServer:
    """The terminal daemon — holds PTY sessions, serves clients over Unix socket."""

    def __init__(self) -> None:
        self._manager = TerminalManager()
        self._attachments: dict[str, set[asyncio.StreamWriter]] = {}  # terminal_id → writers

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle one client connection (from the web server)."""
        attached_terminal: str | None = None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                cmd = msg.get("cmd", "")
                if cmd == "spawn":
                    resp = self._handle_spawn(msg)
                elif cmd == "list":
                    resp = self._handle_list()
                elif cmd == "close":
                    resp = self._handle_close(msg)
                elif cmd == "resize":
                    resp = self._handle_resize(msg)
                elif cmd == "attach":
                    resp = self._handle_attach(msg, writer)
                    if resp.get("ok"):
                        attached_terminal = msg.get("terminal_id", "")
                elif cmd == "detach":
                    if attached_terminal:
                        self._detach(attached_terminal, writer)
                        attached_terminal = None
                    resp = {"ok": True}
                elif cmd == "input":
                    self._handle_input(msg)
                    continue  # no response for input (fire and forget)
                else:
                    resp = {"ok": False, "error": f"Unknown command: {cmd}"}

                writer.write(json.dumps(resp).encode() + b"\n")
                await writer.drain()

        except (asyncio.CancelledError, ConnectionError):
            pass
        finally:
            if attached_terminal:
                self._detach(attached_terminal, writer)
            writer.close()

    def _handle_spawn(self, msg: dict[str, Any]) -> dict[str, Any]:
        target_id = msg.get("target_id", "local")
        command = msg.get("command")
        cols = msg.get("cols", 120)
        rows = msg.get("rows", 30)
        cwd = msg.get("cwd")
        cmd_list = command if isinstance(command, list) else (
            command.split() if isinstance(command, str) else None
        )
        session = self._manager.spawn(target_id, command=cmd_list, cols=cols, rows=rows, cwd=cwd)
        # Start reading PTY output and forwarding to attached clients
        asyncio.get_event_loop().create_task(self._read_loop(session))
        return {
            "ok": True,
            "terminal_id": session.terminal_id,
            "target_id": session.target_id,
            "title": session.title,
        }

    def _handle_list(self) -> dict[str, Any]:
        terminals = self._manager.list_sessions()
        return {
            "ok": True,
            "terminals": [
                {
                    "terminal_id": t.terminal_id,
                    "target_id": t.target_id,
                    "title": t.title,
                    "cols": t.cols,
                    "rows": t.rows,
                    "alive": t.alive,
                }
                for t in terminals
            ],
        }

    def _handle_close(self, msg: dict[str, Any]) -> dict[str, Any]:
        terminal_id = msg.get("terminal_id", "")
        ok = self._manager.close_session(terminal_id)
        # Notify attached clients by closing their connection
        if terminal_id in self._attachments:
            del self._attachments[terminal_id]
        return {"ok": ok}

    def _handle_resize(self, msg: dict[str, Any]) -> dict[str, Any]:
        terminal_id = msg.get("terminal_id", "")
        session = self._manager.get_session(terminal_id)
        if session:
            session.resize(msg.get("cols", session.cols), msg.get("rows", session.rows))
            return {"ok": True}
        return {"ok": False, "error": "Terminal not found"}

    def _handle_attach(
        self, msg: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        terminal_id = msg.get("terminal_id", "")
        session = self._manager.get_session(terminal_id)
        if session is None:
            return {"ok": False, "error": "Terminal not found"}
        # Add writer to attachments
        if terminal_id not in self._attachments:
            self._attachments[terminal_id] = set()
        self._attachments[terminal_id].add(writer)
        # Return scrollback as base64
        scrollback = session.scrollback
        return {
            "ok": True,
            "scrollback": base64.b64encode(scrollback).decode() if scrollback else "",
        }

    def _detach(self, terminal_id: str, writer: asyncio.StreamWriter) -> None:
        if terminal_id in self._attachments:
            self._attachments[terminal_id].discard(writer)

    def _handle_input(self, msg: dict[str, Any]) -> None:
        terminal_id = msg.get("terminal_id", "")
        data_b64 = msg.get("data", "")
        session = self._manager.get_session(terminal_id)
        if session and data_b64:
            session.write(base64.b64decode(data_b64))

    async def _read_loop(self, session: TerminalSession) -> None:
        """Read PTY output and forward to all attached clients."""
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def on_readable() -> None:
            try:
                data = os.read(session._master_fd, 65536)
                if data:
                    queue.put_nowait(data)
                else:
                    queue.put_nowait(b"")
            except OSError:
                queue.put_nowait(b"")

        loop.add_reader(session._master_fd, on_readable)
        try:
            while session.alive:
                data = await queue.get()
                if not data:
                    break
                # Update scrollback
                session._scrollback.extend(data)
                max_sb = 200 * 1024
                if len(session._scrollback) > max_sb:
                    del session._scrollback[:len(session._scrollback) - max_sb]
                # Forward to attached clients as base64 JSON
                writers = self._attachments.get(session.terminal_id, set())
                dead: list[asyncio.StreamWriter] = []
                frame = json.dumps({"out": base64.b64encode(data).decode()}).encode() + b"\n"
                for w in writers:
                    try:
                        w.write(frame)
                        await w.drain()
                    except Exception:
                        dead.append(w)
                for w in dead:
                    writers.discard(w)
        finally:
            try:
                loop.remove_reader(session._master_fd)
            except Exception:
                pass


async def run_daemon() -> None:
    """Start the terminal daemon."""
    # Remove stale socket
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    daemon = DaemonServer()
    server = await asyncio.start_unix_server(
        daemon.handle_client, path=str(SOCKET_PATH)
    )
    # Make socket accessible
    os.chmod(str(SOCKET_PATH), 0o600)

    logger.info("hort-termd listening on %s", SOCKET_PATH)
    print(f"hort-termd listening on {SOCKET_PATH}", flush=True)

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, server.close)

    async with server:
        await server.serve_forever()


def main() -> None:
    """Entry point for the terminal daemon."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        asyncio.run(run_daemon())
    except KeyboardInterrupt:
        pass
    finally:
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()


if __name__ == "__main__":
    main()
