"""Managed subprocess lifecycle — spawn, reconnect, shutdown, orphan cleanup.

Each ManagedProcess:
- Runs as a separate OS process
- Communicates with the main process via Unix domain socket (IPC)
- Survives uvicorn hot reloads
- Has a PID file for orphan detection
- Has a protocol version for compatibility checking
- Auto-restarts on crash (with backoff)

The ProcessManager coordinates all managed processes for the hort instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def _pid_dir() -> Path:
    from hort.paths import pid_dir
    return pid_dir()


def _ipc_dir() -> Path:
    from hort.paths import ipc_dir
    return ipc_dir()


def _ensure_dirs() -> None:
    _pid_dir()
    _ipc_dir()


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    # Check for zombies (killed but not waited on)
    try:
        result = os.waitpid(pid, os.WNOHANG)
        if result[0] != 0:
            return False  # reaped zombie
    except ChildProcessError:
        pass  # not our child — can't waitpid, but kill(0) worked so it's alive
    return True


class ManagedProcess(ABC):
    """Base class for a managed subprocess.

    Subclass this and implement:
    - ``name`` — unique identifier (e.g. "telegram", "mcp-bridge")
    - ``protocol_version`` — bump when IPC message format changes
    - ``build_command()`` — the subprocess command to run
    - ``on_message()`` — handle messages from the subprocess

    The framework handles:
    - PID files and orphan cleanup
    - IPC via Unix domain socket
    - Protocol version checking on reconnect
    - Auto-restart on crash (with exponential backoff)
    - Clean shutdown (SIGTERM → wait → SIGKILL)
    """

    name: str = ""
    protocol_version: int = 1

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._ipc_server: asyncio.Server | None = None
        self._ipc_reader: asyncio.StreamReader | None = None
        self._ipc_writer: asyncio.StreamWriter | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._connected = False
        self._restart_count = 0
        self._last_restart = 0.0
        self._stopping = False

    @property
    def pid_file(self) -> Path:
        return _pid_dir() / f"{self.name}.pid"

    @property
    def ipc_path(self) -> str:
        return str(_ipc_dir() / f"{self.name}.sock")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── Abstract interface ──

    @abstractmethod
    def build_command(self) -> list[str]:
        """Return the command to start the subprocess."""
        ...

    async def on_message(self, msg: dict[str, Any]) -> None:
        """Handle a message from the subprocess. Override in subclass."""

    async def on_connected(self) -> None:
        """Called when IPC connection is established. Override for init."""

    async def on_disconnected(self) -> None:
        """Called when IPC connection drops. Override for cleanup."""

    def get_env(self) -> dict[str, str] | None:
        """Extra environment variables for the subprocess. Override if needed."""
        return None

    # ── Lifecycle ──

    async def start(self) -> bool:
        """Start or reconnect to the subprocess."""
        _ensure_dirs()

        # Try to reconnect to existing subprocess first
        if await self._try_reconnect():
            return True

        # Kill any orphan
        self._cleanup_orphan()

        # Clean up stale socket
        try:
            os.unlink(self.ipc_path)
        except FileNotFoundError:
            pass

        # Start IPC server (main listens, subprocess connects)
        self._ipc_server = await asyncio.start_unix_server(
            self._handle_ipc_connection, self.ipc_path,
        )

        # Spawn subprocess
        cmd = self.build_command()
        env = {**os.environ, "HORT_IPC_PATH": self.ipc_path}
        extra = self.get_env()
        if extra:
            env.update(extra)

        self._proc = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        # Write PID file
        self.pid_file.write_text(str(self._proc.pid))
        logger.info("[%s] Subprocess started (PID %d)", self.name, self._proc.pid)

        # Start health monitor
        self._stopping = False
        self._monitor_task = asyncio.create_task(self._monitor_loop())

        # Wait for subprocess to connect (up to 10s)
        for _ in range(100):
            if self._connected:
                return True
            await asyncio.sleep(0.1)

        logger.warning("[%s] Subprocess started but IPC not connected after 10s", self.name)
        return self.running

    async def stop(self) -> None:
        """Stop the subprocess and clean up."""
        self._stopping = True

        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None

        if self._ipc_writer:
            try:
                await self.send({"type": "shutdown"})
            except Exception:
                pass
            self._ipc_writer.close()
            self._ipc_writer = None
            self._ipc_reader = None
            self._connected = False

        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
            logger.info("[%s] Subprocess stopped (PID %d)", self.name, self._proc.pid)

        self._proc = None

        if self._ipc_server:
            self._ipc_server.close()
            self._ipc_server = None

        # Clean up files
        try:
            self.pid_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            os.unlink(self.ipc_path)
        except Exception:
            pass

    async def detach(self) -> None:
        """Disconnect IPC but leave the subprocess running (for hot reload)."""
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None

        if self._ipc_writer:
            try:
                await self.send({"type": "detach"})
            except Exception:
                pass
            self._ipc_writer.close()
            self._ipc_writer = None
            self._ipc_reader = None
            self._connected = False

        if self._ipc_server:
            self._ipc_server.close()
            self._ipc_server = None

        # Do NOT kill the process or remove PID file
        self._proc = None
        logger.info("[%s] Detached (subprocess keeps running)", self.name)

    async def send(self, msg: dict[str, Any]) -> None:
        """Send a message to the subprocess via IPC."""
        if not self._ipc_writer:
            raise ConnectionError(f"[{self.name}] Not connected")
        data = json.dumps(msg) + "\n"
        self._ipc_writer.write(data.encode())
        await self._ipc_writer.drain()

    # ── IPC handling ──

    async def _handle_ipc_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        """Subprocess connected to our IPC socket."""
        logger.info("[%s] IPC connection established", self.name)
        self._ipc_reader = reader
        self._ipc_writer = writer
        self._connected = True
        self._restart_count = 0

        # Version handshake
        try:
            hello_line = await asyncio.wait_for(reader.readline(), timeout=5)
            hello = json.loads(hello_line.decode())
            remote_version = hello.get("protocol_version", 0)
            if remote_version != self.protocol_version:
                logger.warning(
                    "[%s] Protocol mismatch: local=%d remote=%d — restarting subprocess",
                    self.name, self.protocol_version, remote_version,
                )
                writer.close()
                self._connected = False
                await self._restart()
                return

            # Send ack
            ack = json.dumps({"type": "hello_ack", "protocol_version": self.protocol_version}) + "\n"
            writer.write(ack.encode())
            await writer.drain()
        except Exception:
            logger.exception("[%s] Handshake failed", self.name)
            writer.close()
            self._connected = False
            return

        await self.on_connected()

        # Read messages
        try:
            while self._connected:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                    await self.on_message(msg)
                except json.JSONDecodeError:
                    continue
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._connected = False
            self._ipc_writer = None
            self._ipc_reader = None
            await self.on_disconnected()
            logger.info("[%s] IPC disconnected", self.name)

    # ── Reconnect to existing subprocess ──

    async def _try_reconnect(self) -> bool:
        """Try to reconnect to an existing subprocess (after hot reload)."""
        if not self.pid_file.exists():
            return False

        try:
            pid = int(self.pid_file.read_text().strip())
        except (ValueError, OSError):
            return False

        if not _process_alive(pid):
            self.pid_file.unlink(missing_ok=True)
            return False

        # Process is alive — start IPC server and wait for connection
        logger.info("[%s] Found running subprocess (PID %d), reconnecting", self.name, pid)

        try:
            os.unlink(self.ipc_path)
        except FileNotFoundError:
            pass

        self._ipc_server = await asyncio.start_unix_server(
            self._handle_ipc_connection, self.ipc_path,
        )

        # Signal the subprocess to reconnect
        os.kill(pid, signal.SIGUSR1)

        # Wait for connection
        for _ in range(50):
            if self._connected:
                logger.info("[%s] Reconnected to existing subprocess", self.name)
                self._stopping = False
                self._monitor_task = asyncio.create_task(self._monitor_loop())
                return True
            await asyncio.sleep(0.1)

        logger.warning("[%s] Subprocess alive but didn't reconnect — killing", self.name)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        self.pid_file.unlink(missing_ok=True)
        if self._ipc_server:
            self._ipc_server.close()
            self._ipc_server = None
        return False

    # ── Health monitor ──

    async def _monitor_loop(self) -> None:
        """Watch the subprocess, restart on crash."""
        while not self._stopping:
            await asyncio.sleep(2)
            if self._stopping:
                break

            if self._proc and self._proc.poll() is not None:
                exit_code = self._proc.returncode
                logger.warning("[%s] Subprocess died (exit %d)", self.name, exit_code)
                self._proc = None
                self._connected = False

                if not self._stopping:
                    await self._restart()

    async def _restart(self) -> None:
        """Restart the subprocess with exponential backoff."""
        self._restart_count += 1
        backoff = min(2 ** self._restart_count, 30)
        logger.info("[%s] Restarting in %ds (attempt %d)", self.name, backoff, self._restart_count)
        await asyncio.sleep(backoff)

        if self._stopping:
            return

        # Kill old process if still around
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(timeout=2)
        self._proc = None

        # Clean up old IPC
        if self._ipc_server:
            self._ipc_server.close()
        try:
            os.unlink(self.ipc_path)
        except FileNotFoundError:
            pass

        # Re-start
        await self.start()

    def _cleanup_orphan(self) -> None:
        """Kill an orphan subprocess from a previous crash."""
        if not self.pid_file.exists():
            return
        try:
            pid = int(self.pid_file.read_text().strip())
        except (ValueError, OSError):
            self.pid_file.unlink(missing_ok=True)
            return

        if _process_alive(pid):
            logger.info("[%s] Killing orphan subprocess (PID %d)", self.name, pid)
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if _process_alive(pid):
                os.kill(pid, signal.SIGKILL)
        self.pid_file.unlink(missing_ok=True)


class ProcessManager:
    """Manages all ManagedProcesses for a hort instance.

    Usage::

        pm = ProcessManager()
        pm.register(TelegramPoller())
        pm.register(MCPBridge())
        await pm.start_all()

        # On hot reload (shutdown handler):
        await pm.detach_all()  # keep subprocesses alive

        # On hort stop:
        await pm.stop_all()    # kill everything
    """

    def __init__(self) -> None:
        self._processes: dict[str, ManagedProcess] = {}

    def register(self, proc: ManagedProcess) -> None:
        self._processes[proc.name] = proc

    def get(self, name: str) -> ManagedProcess | None:
        return self._processes.get(name)

    async def start_all(self) -> None:
        """Start or reconnect all managed processes."""
        for proc in self._processes.values():
            try:
                await proc.start()
            except Exception:
                logger.exception("[%s] Failed to start", proc.name)

    async def stop_all(self) -> None:
        """Stop all managed processes (clean shutdown)."""
        for proc in self._processes.values():
            try:
                await proc.stop()
            except Exception:
                logger.exception("[%s] Failed to stop", proc.name)

    async def detach_all(self) -> None:
        """Detach from all subprocesses (hot reload — keep them alive)."""
        for proc in self._processes.values():
            try:
                await proc.detach()
            except Exception:
                logger.exception("[%s] Failed to detach", proc.name)

    @staticmethod
    def cleanup_all_orphans() -> None:
        """Kill all orphan subprocesses from previous crashes."""
        _ensure_dirs()
        for pid_file in _pid_dir().glob("*.pid"):
            if pid_file.name == "main.pid":
                continue
            try:
                pid = int(pid_file.read_text().strip())
                if _process_alive(pid):
                    logger.info("Killing orphan: %s (PID %d)", pid_file.stem, pid)
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.5)
            except Exception:
                pass
            pid_file.unlink(missing_ok=True)
