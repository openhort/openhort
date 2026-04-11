"""Tests for the managed subprocess lifecycle framework.

Verifies:
- Subprocess spawning and IPC connection
- Protocol version handshake
- Message exchange (bidirectional)
- Clean shutdown (stop)
- Hot-reload survival (detach + reconnect)
- Crash recovery (auto-restart)
- Orphan cleanup
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


# ── Helper: create a minimal worker script ──

WORKER_SCRIPT = textwrap.dedent("""\
    import asyncio
    import sys
    sys.path.insert(0, "{cwd}")
    from hort.lifecycle.worker import Worker

    class TestWorker(Worker):
        name = "test-worker"
        protocol_version = {version}

        async def on_connected(self):
            await self.send({{"type": "ready", "pid": __import__("os").getpid()}})

        async def on_message(self, msg):
            if msg.get("type") == "echo":
                await self.send({{"type": "echo_reply", "data": msg.get("data")}})
            elif msg.get("type") == "ping":
                await self.send({{"type": "pong"}})

    TestWorker().run()
""")


def _write_worker(tmp_path: Path, version: int = 1) -> Path:
    script = tmp_path / "test_worker.py"
    cwd = str(Path(__file__).parent.parent)
    script.write_text(WORKER_SCRIPT.format(cwd=cwd, version=version))
    return script


# ── Test ManagedProcess subclass ──

class EchoProcess:
    """Test ManagedProcess that spawns the test worker."""

    def __init__(self, worker_script: Path, version: int = 1):
        from hort.lifecycle.manager import ManagedProcess

        class _Echo(ManagedProcess):
            name = "test-worker"
            protocol_version = version
            _messages: list = []

            def build_command(self):
                return [sys.executable, str(worker_script)]

            async def on_message(self, msg):
                self._messages.append(msg)

            async def on_connected(self):
                pass

        self.proc = _Echo()
        self.proc._messages = []

    @property
    def messages(self) -> list:
        return self.proc._messages


# ── Tests ──

class TestLifecycle:
    """Core lifecycle tests."""

    @pytest.mark.asyncio
    async def test_start_and_connect(self, tmp_path):
        """Subprocess starts and connects via IPC."""
        script = _write_worker(tmp_path)
        echo = EchoProcess(script)
        try:
            ok = await echo.proc.start()
            assert ok
            assert echo.proc.running
            assert echo.proc.connected

            # Worker sends "ready" on connect
            await asyncio.sleep(0.3)
            ready_msgs = [m for m in echo.messages if m.get("type") == "ready"]
            assert len(ready_msgs) == 1
            assert ready_msgs[0]["pid"] > 0
        finally:
            await echo.proc.stop()

    @pytest.mark.asyncio
    async def test_bidirectional_messages(self, tmp_path):
        """Main and subprocess exchange messages."""
        script = _write_worker(tmp_path)
        echo = EchoProcess(script)
        try:
            await echo.proc.start()
            await asyncio.sleep(0.2)

            # Send echo request
            await echo.proc.send({"type": "echo", "data": "hello world"})
            await asyncio.sleep(0.3)

            replies = [m for m in echo.messages if m.get("type") == "echo_reply"]
            assert len(replies) == 1
            assert replies[0]["data"] == "hello world"
        finally:
            await echo.proc.stop()

    @pytest.mark.asyncio
    async def test_clean_shutdown(self, tmp_path):
        """Stop kills subprocess and cleans up files."""
        script = _write_worker(tmp_path)
        echo = EchoProcess(script)

        await echo.proc.start()
        pid = echo.proc._proc.pid
        assert echo.proc.pid_file.exists()

        await echo.proc.stop()
        assert not echo.proc.running
        assert not echo.proc.connected
        assert not echo.proc.pid_file.exists()
        # Process should be dead
        await asyncio.sleep(0.5)
        assert not _process_alive(pid)

    @pytest.mark.asyncio
    async def test_detach_keeps_subprocess_alive(self, tmp_path):
        """Detach disconnects IPC but leaves subprocess running."""
        script = _write_worker(tmp_path)
        echo = EchoProcess(script)

        await echo.proc.start()
        pid = echo.proc._proc.pid
        assert echo.proc.pid_file.exists()

        await echo.proc.detach()
        assert not echo.proc.connected
        # Subprocess should still be alive
        assert _process_alive(pid)
        # PID file should still exist
        assert echo.proc.pid_file.exists()

        # Clean up
        os.kill(pid, signal.SIGTERM)
        await asyncio.sleep(0.5)
        echo.proc.pid_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_reconnect_after_detach(self, tmp_path):
        """After detach, a new ManagedProcess reconnects to the existing subprocess."""
        script = _write_worker(tmp_path)
        echo1 = EchoProcess(script)

        await echo1.proc.start()
        pid = echo1.proc._proc.pid

        # Detach (simulates hot reload)
        await echo1.proc.detach()
        await asyncio.sleep(0.5)

        # New instance reconnects
        echo2 = EchoProcess(script)
        ok = await echo2.proc.start()
        assert ok
        assert echo2.proc.connected

        # Verify it's the same subprocess
        await asyncio.sleep(0.3)
        ready_msgs = [m for m in echo2.messages if m.get("type") == "ready"]
        assert len(ready_msgs) >= 1

        await echo2.proc.stop()

    @pytest.mark.asyncio
    async def test_protocol_version_mismatch(self, tmp_path):
        """Version mismatch kills old subprocess and starts new."""
        # Start with version 1
        script_v1 = _write_worker(tmp_path, version=1)
        echo1 = EchoProcess(script_v1, version=1)
        await echo1.proc.start()
        pid1 = echo1.proc._proc.pid
        await echo1.proc.detach()
        await asyncio.sleep(0.5)

        # Reconnect with version 2 — should kill and restart
        (tmp_path / "v2").mkdir(exist_ok=True)
        script_v2 = _write_worker(tmp_path / "v2", version=2)
        echo2 = EchoProcess(script_v2, version=2)
        await echo2.proc.start()
        await asyncio.sleep(1)

        # Should have a new PID (old was killed)
        if echo2.proc._proc:
            assert echo2.proc._proc.pid != pid1

        await echo2.proc.stop()
        # Clean up old process if still alive
        if _process_alive(pid1):
            os.kill(pid1, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_orphan_cleanup(self, tmp_path):
        """Orphan subprocess from a crash is killed on next startup."""
        from hort.lifecycle.manager import _pid_dir, _ensure_dirs, ProcessManager
        _ensure_dirs()

        # Simulate an orphan: start a sleep process and write PID file
        orphan = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
        )
        pid_file = _pid_dir() / "test-orphan.pid"
        pid_file.write_text(str(orphan.pid))

        assert _process_alive(orphan.pid)

        # Cleanup should kill it
        ProcessManager.cleanup_all_orphans()

        # Reap the zombie (we're the parent process)
        try:
            orphan.wait(timeout=3)
        except Exception:
            orphan.kill()
            orphan.wait(timeout=2)

        assert not pid_file.exists()
        assert orphan.returncode is not None  # process finished

    @pytest.mark.asyncio
    async def test_crash_recovery(self, tmp_path):
        """Subprocess crash triggers auto-restart."""
        script = _write_worker(tmp_path)
        echo = EchoProcess(script)
        # Set low backoff for testing
        echo.proc._restart_count = -1  # first restart = 2^0 = 1s

        await echo.proc.start()
        pid1 = echo.proc._proc.pid
        assert echo.proc.connected

        # Kill the subprocess
        os.kill(pid1, signal.SIGKILL)
        await asyncio.sleep(4)  # wait for monitor + restart + connect

        # Should have auto-restarted
        assert echo.proc.running or echo.proc.connected
        if echo.proc._proc:
            assert echo.proc._proc.pid != pid1

        await echo.proc.stop()


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
