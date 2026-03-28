"""Bridge to the openhort server — manages subprocess lifecycle and API polling."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# Default openhort ports (matches hort/app.py)
HTTP_PORT = 8940
HTTPS_PORT = 8950
POLL_INTERVAL = 3.0  # seconds between status polls


@dataclass
class ServerStatus:
    """Snapshot of the openhort server state."""

    running: bool = False
    observers: int = 0
    version: str = ""
    http_url: str = ""
    https_url: str = ""
    targets: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class ServerBridge:
    """Manages the openhort server process and polls its API for status.

    The bridge can:
    - Start/stop the server as a subprocess
    - Detect an already-running server
    - Poll /api/hash and the control WebSocket for live status
    - Notify a callback on status changes
    """

    def __init__(
        self,
        project_root: Path | None = None,
        on_status_change: Callable[[ServerStatus], None] | None = None,
    ) -> None:
        self._project_root = project_root or self._find_project_root()
        self._on_status_change = on_status_change
        self._process: subprocess.Popen[bytes] | None = None
        self._status = ServerStatus()
        self._poll_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._http = httpx.AsyncClient(verify=False, timeout=5.0)

    @property
    def status(self) -> ServerStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status.running

    # --- Server process management ---

    def start_server(self) -> None:
        """Start the openhort server as a subprocess."""
        if self._process and self._process.poll() is None:
            logger.info("Server already running (PID %d)", self._process.pid)
            return

        if self._is_port_in_use():
            logger.info("Port %d already in use — server likely running externally", HTTP_PORT)
            self._status.running = True
            self._notify()
            return

        env = os.environ.copy()
        env["LLMING_DEV"] = "0"  # production mode

        run_py = self._project_root / "run.py"
        if not run_py.exists():
            self._status.error = f"run.py not found at {run_py}"
            self._notify()
            return

        logger.info("Starting openhort server from %s", run_py)
        self._process = subprocess.Popen(
            [sys.executable, str(run_py)],
            cwd=str(self._project_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._status.running = True
        self._status.error = None
        self._notify()

    def stop_server(self) -> None:
        """Stop the server subprocess gracefully."""
        if self._process and self._process.poll() is None:
            logger.info("Stopping server (PID %d)", self._process.pid)
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Server didn't stop in 5s, sending SIGKILL")
                self._process.kill()
                self._process.wait(timeout=3)
            self._process = None
        else:
            # Try to kill by process name (external server)
            self._kill_external_server()

        self._status = ServerStatus()
        self._notify()

    def _kill_external_server(self) -> None:
        """Kill an externally-started openhort server by process name."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "uvicorn hort.app"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                logger.info("Killed external server PIDs: %s", pids)
        except Exception as e:
            logger.warning("Failed to kill external server: %s", e)

    # --- Status polling ---

    async def start_polling(self) -> None:
        """Start the background status polling loop."""
        self._loop = asyncio.get_running_loop()
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_polling(self) -> None:
        """Stop polling."""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await self._http.aclose()

    async def _poll_loop(self) -> None:
        """Poll the server API at regular intervals."""
        while True:
            await self._poll_once()
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_once(self) -> None:
        """Single poll cycle — check server health and gather status."""
        old_status = ServerStatus(
            running=self._status.running,
            observers=self._status.observers,
        )

        # Check if subprocess is still alive
        if self._process and self._process.poll() is not None:
            exit_code = self._process.returncode
            self._process = None
            self._status.running = False
            self._status.error = f"Server exited with code {exit_code}"
            if old_status.running:
                self._notify()
            return

        try:
            resp = await self._http.get(f"http://localhost:{HTTP_PORT}/api/hash")
            if resp.status_code == 200:
                self._status.running = True
                self._status.error = None
                self._status.http_url = f"http://localhost:{HTTP_PORT}"

                # Get observer count via a quick session + status check
                await self._poll_observers()
            else:
                self._status.running = False
        except httpx.ConnectError:
            self._status.running = self._process is not None and self._process.poll() is None
            if not self._status.running:
                self._status.observers = 0
        except Exception as e:
            logger.debug("Poll error: %s", e)

        if (
            old_status.running != self._status.running
            or old_status.observers != self._status.observers
        ):
            self._notify()

    async def _poll_observers(self) -> None:
        """Get the current observer count from the server."""
        try:
            # Create a temporary session to query status
            resp = await self._http.post(f"http://localhost:{HTTP_PORT}/api/session")
            if resp.status_code != 200:
                return
            session_id = resp.json().get("session_id", "")
            if not session_id:
                return

            # Connect via WebSocket briefly to get status
            import websockets

            uri = f"ws://localhost:{HTTP_PORT}/ws/control/{session_id}"
            async with websockets.connect(uri, close_timeout=2) as ws:
                await ws.send(json.dumps({"type": "get_status"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                msg = json.loads(raw)
                if msg.get("type") == "status":
                    # Subtract 1 because our polling session counts as an observer
                    self._status.observers = max(0, msg.get("observers", 0) - 1)
                    self._status.version = msg.get("version", "")
        except Exception as e:
            logger.debug("Observer poll error: %s", e)

    # --- Helpers ---

    def _is_port_in_use(self) -> bool:
        """Check if the HTTP port is in use."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("localhost", HTTP_PORT)) == 0

    def _find_project_root(self) -> Path:
        """Find the openhort project root by walking up from this file."""
        # Look for the parent openhort project
        p = Path(__file__).resolve()
        while p != p.parent:
            if (p / "run.py").exists() and (p / "hort" / "app.py").exists():
                return p
            p = p.parent
        # Fallback: assume we're in subprojects/macos_statusbar/
        return Path(__file__).resolve().parent.parent.parent

    def _notify(self) -> None:
        """Call the status change callback."""
        if self._on_status_change:
            try:
                self._on_status_change(self._status)
            except Exception:
                logger.exception("Status change callback failed")
