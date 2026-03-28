"""Tests for ServerBridge — server lifecycle and status polling."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from hort_statusbar.server_bridge import ServerBridge, ServerStatus


class TestServerStatus:
    def test_defaults(self) -> None:
        s = ServerStatus()
        assert not s.running
        assert s.observers == 0
        assert s.version == ""
        assert s.error is None

    def test_fields(self) -> None:
        s = ServerStatus(running=True, observers=3, version="0.1.0")
        assert s.running
        assert s.observers == 3


class TestServerBridge:
    def test_find_project_root(self) -> None:
        bridge = ServerBridge()
        root = bridge._project_root
        # Should find the openhort project root
        assert (root / "hort").is_dir() or root.name == "openhort"

    def test_initial_status(self) -> None:
        bridge = ServerBridge()
        assert not bridge.is_running
        assert bridge.status.observers == 0

    def test_callback_called(self) -> None:
        cb = MagicMock()
        bridge = ServerBridge(on_status_change=cb)
        bridge._status.running = True
        bridge._notify()
        cb.assert_called_once()
        status = cb.call_args[0][0]
        assert status.running

    def test_callback_exception_swallowed(self) -> None:
        cb = MagicMock(side_effect=RuntimeError("boom"))
        bridge = ServerBridge(on_status_change=cb)
        # Should not raise
        bridge._notify()

    def test_port_check(self) -> None:
        bridge = ServerBridge()
        # Port 8940 may or may not be in use, just verify it returns bool
        result = bridge._is_port_in_use()
        assert isinstance(result, bool)

    def test_start_server_missing_run_py(self, tmp_path: Path) -> None:
        cb = MagicMock()
        bridge = ServerBridge(project_root=tmp_path, on_status_change=cb)
        with patch.object(bridge, "_is_port_in_use", return_value=False):
            bridge.start_server()
        assert bridge.status.error is not None
        assert "run.py" in bridge.status.error

    def test_start_when_port_in_use(self) -> None:
        cb = MagicMock()
        bridge = ServerBridge(on_status_change=cb)
        with patch.object(bridge, "_is_port_in_use", return_value=True):
            bridge.start_server()
        assert bridge.status.running

    def test_stop_when_not_running(self) -> None:
        bridge = ServerBridge()
        bridge.stop_server()  # should not raise
        assert not bridge.status.running


class TestPollOnce:
    @pytest.mark.asyncio
    async def test_poll_server_not_reachable(self) -> None:
        cb = MagicMock()
        bridge = ServerBridge(on_status_change=cb)
        # Mock httpx to simulate connection refused
        with patch.object(bridge._http, "get", side_effect=httpx.ConnectError("refused")):
            await bridge._poll_once()
        # No subprocess and connection refused → not running
        assert not bridge.status.running
