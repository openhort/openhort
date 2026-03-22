"""Terminal session management — PTY-backed terminals for local and container hosts.

Each terminal session wraps a real pseudo-terminal (PTY) connected to a
shell process.  For local targets the shell runs directly; for Docker
targets it runs via ``docker exec -it``.

Architecture (VS Code-style):
- Server holds the PTY and a scrollback buffer (last 200 KB)
- Each connected WebSocket receives the scrollback on connect, then live output
- Keystrokes from the WebSocket are written to the PTY
- Multiple viewers can watch the same terminal simultaneously
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
import time
from dataclasses import dataclass, field
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

MAX_SCROLLBACK = 200 * 1024  # 200 KB
DEFAULT_COLS = 120
DEFAULT_ROWS = 30


@dataclass
class TerminalInfo:
    """Serializable terminal metadata."""

    terminal_id: str
    target_id: str
    title: str
    cols: int
    rows: int
    alive: bool
    created_at: float


class TerminalSession:
    """A single terminal backed by a PTY."""

    def __init__(
        self,
        terminal_id: str,
        target_id: str,
        command: list[str],
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
    ) -> None:
        self.terminal_id = terminal_id
        self.target_id = target_id
        self.cols = cols
        self.rows = rows
        self.created_at = time.monotonic()
        self.title = command[-1] if command else "shell"
        self._scrollback = bytearray()
        self._viewers: set[WebSocket] = set()
        # Spawn PTY
        master_fd, slave_fd = pty.openpty()
        self._set_winsize(slave_fd, rows, cols)
        self._master_fd = master_fd
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        self._process = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            preexec_fn=os.setsid,
            close_fds=True,
        )
        os.close(slave_fd)

        # Make master_fd non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    @property
    def alive(self) -> bool:
        """Whether the shell process is still running."""
        return self._process.poll() is None

    @property
    def scrollback(self) -> bytes:
        """Current scrollback buffer contents."""
        return bytes(self._scrollback)

    def info(self) -> TerminalInfo:
        """Return serializable metadata."""
        return TerminalInfo(
            terminal_id=self.terminal_id,
            target_id=self.target_id,
            title=self.title,
            cols=self.cols,
            rows=self.rows,
            alive=self.alive,
            created_at=self.created_at,
        )

    def write(self, data: bytes) -> None:
        """Write input data (keystrokes) to the PTY."""
        if self.alive:
            try:
                os.write(self._master_fd, data)
            except OSError:
                pass

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY."""
        self.cols = cols
        self.rows = rows
        try:
            self._set_winsize(self._master_fd, rows, cols)
        except OSError:
            pass

    def close(self) -> None:
        """Kill the shell process and clean up."""
        try:
            if self.alive:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self._process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.close(self._master_fd)
        except OSError:
            pass

    def add_viewer(self, ws: WebSocket) -> None:
        """Register a WebSocket viewer."""
        self._viewers.add(ws)

    def remove_viewer(self, ws: WebSocket) -> None:
        """Unregister a WebSocket viewer."""
        self._viewers.discard(ws)

    def _blocking_read(self) -> bytes:
        """Read from the PTY master fd (runs in executor).

        Uses a short poll interval (10ms) for low latency, then drains
        all available data in one go to reduce WS frame count.
        """
        import select

        try:
            r, _, _ = select.select([self._master_fd], [], [], 0.01)
            if not r:
                return b""
            # Read first chunk
            data = os.read(self._master_fd, 65536)
            # Drain any remaining data available right now (coalesce)
            while True:
                r2, _, _ = select.select([self._master_fd], [], [], 0)
                if not r2:
                    break
                chunk = os.read(self._master_fd, 65536)
                if not chunk:
                    break
                data += chunk
            return data
        except OSError:
            return b""

    @staticmethod
    def _set_winsize(fd: int, rows: int, cols: int) -> None:
        """Set the terminal window size on a file descriptor."""
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


class TerminalManager:
    """Manages terminal sessions across targets.

    Singleton — use ``TerminalManager.get()``.
    """

    _instance: TerminalManager | None = None

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}

    @classmethod
    def get(cls) -> TerminalManager:
        """Get or create the singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing). Closes all sessions."""
        if cls._instance:
            for session in cls._instance._sessions.values():
                session.close()
        cls._instance = None

    def spawn(
        self,
        target_id: str,
        command: list[str] | None = None,
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
    ) -> TerminalSession:
        """Spawn a new terminal session."""
        import secrets

        terminal_id = secrets.token_urlsafe(16)
        cmd = command or _default_command(target_id)
        session = TerminalSession(terminal_id, target_id, cmd, cols, rows)
        self._sessions[terminal_id] = session
        return session

    def get_session(self, terminal_id: str) -> TerminalSession | None:
        """Get a terminal session by ID."""
        return self._sessions.get(terminal_id)

    def close_session(self, terminal_id: str) -> bool:
        """Close and remove a terminal session."""
        session = self._sessions.pop(terminal_id, None)
        if session is None:
            return False
        session.close()
        return True

    def list_sessions(self) -> list[TerminalInfo]:
        """List all terminal sessions."""
        return [s.info() for s in self._sessions.values()]

    def close_all(self) -> None:
        """Close all terminal sessions."""
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()


def _default_command(target_id: str) -> list[str]:
    """Build the default shell command for a target."""
    if target_id.startswith("docker-"):
        container_name = target_id.removeprefix("docker-")
        return [
            "docker", "exec", "-it",
            "-e", "TERM=xterm-256color",
            container_name, "/bin/bash",
        ]
    # Local target — use the user's default shell
    shell = os.environ.get("SHELL", "/bin/bash")
    return [shell]


async def handle_terminal_ws(
    websocket: WebSocket,
    terminal_id: str,
) -> None:
    """WebSocket handler for a terminal session.

    Runs two concurrent loops:
    - PTY → WS: reads from the PTY and sends to the browser
    - WS → PTY: reads from the browser and writes to the PTY
    """
    manager = TerminalManager.get()
    session = manager.get_session(terminal_id)
    if session is None or not session.alive:
        await websocket.close(code=4004, reason="Terminal not found")
        return

    await websocket.accept()
    session.add_viewer(websocket)

    # Send scrollback
    scrollback = session.scrollback
    if scrollback:
        await websocket.send_bytes(scrollback)

    async def pty_to_ws() -> None:
        """Read from PTY and forward to this WebSocket.

        Uses asyncio add_reader for non-blocking I/O on the PTY fd.
        No executor threads — clean shutdown guaranteed.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def on_pty_readable() -> None:
            try:
                data = os.read(session._master_fd, 65536)
                if data:
                    queue.put_nowait(data)
            except OSError:
                queue.put_nowait(b"")  # Signal EOF

        loop.add_reader(session._master_fd, on_pty_readable)
        try:
            while session.alive:
                data = await queue.get()
                if not data:
                    break
                # Append to scrollback
                session._scrollback.extend(data)
                if len(session._scrollback) > MAX_SCROLLBACK:
                    excess = len(session._scrollback) - MAX_SCROLLBACK
                    del session._scrollback[:excess]
                # Send to all viewers
                dead: list[WebSocket] = []
                for ws in session._viewers:
                    try:
                        await ws.send_bytes(data)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    session._viewers.discard(ws)
        finally:
            loop.remove_reader(session._master_fd)

    async def ws_to_pty() -> None:
        """Read from WebSocket and forward to PTY."""
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.receive":
                    if "bytes" in msg and msg["bytes"]:
                        session.write(msg["bytes"])
                    elif "text" in msg and msg["text"]:
                        import json

                        try:
                            data = json.loads(msg["text"])
                            if data.get("type") == "resize":
                                session.resize(
                                    data.get("cols", session.cols),
                                    data.get("rows", session.rows),
                                )
                        except (json.JSONDecodeError, TypeError):
                            pass
                elif msg["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass

    try:
        # Run both loops concurrently — when either finishes, cancel the other
        done, pending = await asyncio.wait(
            [asyncio.create_task(pty_to_ws()), asyncio.create_task(ws_to_pty())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception as e:
        logger.exception("Terminal WS error: %s", e)
    finally:
        session.remove_viewer(websocket)
