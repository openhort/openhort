"""Tests for hort.terminal — PTY terminal management."""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import AsyncMock, patch

import pytest

from hort.terminal import TerminalManager, TerminalSession, _default_command


class TestDefaultCommand:
    def test_local(self) -> None:
        cmd = _default_command("local-macos")
        assert cmd == [os.environ.get("SHELL", "/bin/bash")]

    def test_docker(self) -> None:
        cmd = _default_command("docker-my-container")
        assert "docker" in cmd
        assert "exec" in cmd
        assert "my-container" in cmd
        assert "/bin/bash" in cmd


class TestTerminalManager:
    def setup_method(self) -> None:
        TerminalManager.reset()

    def teardown_method(self) -> None:
        TerminalManager.reset()

    def test_singleton(self) -> None:
        m1 = TerminalManager.get()
        m2 = TerminalManager.get()
        assert m1 is m2

    def test_spawn_and_list(self) -> None:
        mgr = TerminalManager.get()
        session = mgr.spawn("local", command=["/bin/sh"])
        assert session.alive
        sessions = mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].terminal_id == session.terminal_id

    def test_get_session(self) -> None:
        mgr = TerminalManager.get()
        session = mgr.spawn("local", command=["/bin/sh"])
        got = mgr.get_session(session.terminal_id)
        assert got is session
        assert mgr.get_session("nonexistent") is None

    def test_close_session(self) -> None:
        mgr = TerminalManager.get()
        session = mgr.spawn("local", command=["/bin/sh"])
        tid = session.terminal_id
        assert mgr.close_session(tid)
        assert not session.alive
        assert mgr.get_session(tid) is None
        assert not mgr.close_session("nonexistent")

    def test_close_all(self) -> None:
        mgr = TerminalManager.get()
        mgr.spawn("local", command=["/bin/sh"])
        mgr.spawn("local", command=["/bin/sh"])
        assert len(mgr.list_sessions()) == 2
        mgr.close_all()
        assert len(mgr.list_sessions()) == 0


class TestTerminalSession:
    def setup_method(self) -> None:
        TerminalManager.reset()

    def teardown_method(self) -> None:
        TerminalManager.reset()

    def test_write_and_read(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"], cols=80, rows=24)
        try:
            # Write a command
            session.write(b"echo hello_test_marker\n")
            time.sleep(0.5)

            # Read from PTY via the blocking read method
            data = session._blocking_read()
            # The output should contain our command or its output
            all_data = data or b""
            for _ in range(10):
                chunk = session._blocking_read()
                if chunk:
                    all_data += chunk
                else:
                    break
            assert b"hello_test_marker" in all_data
        finally:
            session.close()

    def test_resize(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"])
        try:
            session.resize(100, 40)
            assert session.cols == 100
            assert session.rows == 40
        finally:
            session.close()

    def test_info(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"])
        try:
            info = session.info()
            assert info.terminal_id == "t1"
            assert info.target_id == "local"
            assert info.alive
            assert info.cols == 120
        finally:
            session.close()

    def test_close_kills_process(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"])
        assert session.alive
        session.close()
        assert not session.alive

    def test_scrollback_buffer(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"])
        try:
            session.write(b"echo scrollback_test_data\n")
            time.sleep(0.5)
            # Manually read to populate scrollback
            for _ in range(10):
                chunk = session._blocking_read()
                if chunk:
                    session._scrollback.extend(chunk)
                else:
                    break
            assert b"scrollback_test_data" in session.scrollback
        finally:
            session.close()

    def test_viewer_management(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"])
        try:
            ws1 = AsyncMock()
            ws2 = AsyncMock()
            session.add_viewer(ws1)
            session.add_viewer(ws2)
            assert len(session._viewers) == 2
            session.remove_viewer(ws1)
            assert len(session._viewers) == 1
            session.remove_viewer(ws1)  # idempotent
            assert len(session._viewers) == 1
        finally:
            session.close()

    def test_write_after_close(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"])
        session.close()
        session.write(b"should not crash\n")  # should not raise

    def test_resize_after_close(self) -> None:
        session = TerminalSession("t1", "local", ["/bin/sh"])
        session.close()
        session.resize(80, 24)  # should not raise


class TestTerminalController:
    """Test terminal messages via the controller."""

    def setup_method(self) -> None:
        TerminalManager.reset()

    def teardown_method(self) -> None:
        TerminalManager.reset()

    def test_spawn_via_controller(self) -> None:
        from hort.controller import HortController
        from hort.session import HortSessionEntry
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        ctrl = HortController("test")
        ws = AsyncMock()
        ctrl.set_websocket(ws)
        ctrl.set_session_entry(HortSessionEntry(user_id="test"))

        asyncio.get_event_loop().run_until_complete(
            ctrl.handle_message({
                "type": "terminal_spawn",
                "target_id": "local",
                "command": "/bin/sh",
            })
        )

        import json

        msgs = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
        assert msgs[0]["type"] == "terminal_spawned"
        assert "terminal_id" in msgs[0]

    def test_list_via_controller(self) -> None:
        from hort.controller import HortController
        from hort.session import HortSessionEntry
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        ctrl = HortController("test")
        ws = AsyncMock()
        ctrl.set_websocket(ws)
        ctrl.set_session_entry(HortSessionEntry(user_id="test"))

        # Spawn one first
        mgr = TerminalManager.get()
        mgr.spawn("local", command=["/bin/sh"])

        asyncio.get_event_loop().run_until_complete(
            ctrl.handle_message({"type": "terminal_list"})
        )

        import json

        msgs = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
        assert msgs[0]["type"] == "terminal_list"
        assert len(msgs[0]["terminals"]) == 1

    def test_close_via_controller(self) -> None:
        from hort.controller import HortController
        from hort.session import HortSessionEntry
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        ctrl = HortController("test")
        ws = AsyncMock()
        ctrl.set_websocket(ws)
        ctrl.set_session_entry(HortSessionEntry(user_id="test"))

        mgr = TerminalManager.get()
        session = mgr.spawn("local", command=["/bin/sh"])

        asyncio.get_event_loop().run_until_complete(
            ctrl.handle_message({
                "type": "terminal_close",
                "terminal_id": session.terminal_id,
            })
        )

        import json

        msgs = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
        assert msgs[0]["type"] == "terminal_closed"
        assert msgs[0]["ok"]

    def test_resize_via_controller(self) -> None:
        from hort.controller import HortController
        from hort.session import HortSessionEntry
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        ctrl = HortController("test")
        ws = AsyncMock()
        ctrl.set_websocket(ws)
        ctrl.set_session_entry(HortSessionEntry(user_id="test"))

        mgr = TerminalManager.get()
        session = mgr.spawn("local", command=["/bin/sh"])

        asyncio.get_event_loop().run_until_complete(
            ctrl.handle_message({
                "type": "terminal_resize",
                "terminal_id": session.terminal_id,
                "cols": 100,
                "rows": 40,
            })
        )

        assert session.cols == 100
        assert session.rows == 40
