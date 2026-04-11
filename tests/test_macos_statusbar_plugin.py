"""Tests for the macOS status bar plugin — subprocess lifecycle and key exchange."""

from __future__ import annotations

import json
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llmings.core.macos_statusbar.provider import (
    HEADER_NAME,
    MacOSStatusBarPlugin,
    _KEY_FILE,
    _KEY_MAX_AGE,
    _STATUSBAR_BIN,
    get_or_rotate_key,
)


def _make_plugin(feature_enabled: bool = True) -> MacOSStatusBarPlugin:
    """Create a plugin instance with a mock context."""
    plugin = MacOSStatusBarPlugin()
    ctx = MagicMock()
    ctx.plugin_id = "macos-statusbar"
    ctx.config.is_feature_enabled.return_value = feature_enabled
    ctx.logger = MagicMock()
    plugin._ctx = ctx
    return plugin


class TestSharedKeyFile:
    """Test the file-based key rotation logic."""

    def test_creates_key_when_missing(self, tmp_path: Path) -> None:
        key_file = tmp_path / "statusbar.key"
        with patch(
            "llmings.core.macos_statusbar.provider._KEY_FILE", key_file
        ):
            key = get_or_rotate_key()
        assert len(key) > 20
        assert key_file.exists()
        data = json.loads(key_file.read_text())
        assert data["key"] == key
        assert time.time() - data["created"] < 5

    def test_reads_existing_fresh_key(self, tmp_path: Path) -> None:
        key_file = tmp_path / "statusbar.key"
        key_file.write_text(json.dumps({"key": "existing-key", "created": time.time()}))
        with patch(
            "llmings.core.macos_statusbar.provider._KEY_FILE", key_file
        ):
            key = get_or_rotate_key()
        assert key == "existing-key"

    def test_rotates_stale_key(self, tmp_path: Path) -> None:
        key_file = tmp_path / "statusbar.key"
        old_time = time.time() - _KEY_MAX_AGE - 100
        key_file.write_text(json.dumps({"key": "old-key", "created": old_time}))
        with patch(
            "llmings.core.macos_statusbar.provider._KEY_FILE", key_file
        ):
            key = get_or_rotate_key()
        assert key != "old-key"
        assert len(key) > 20

    def test_rotates_corrupt_file(self, tmp_path: Path) -> None:
        key_file = tmp_path / "statusbar.key"
        key_file.write_text("not json")
        with patch(
            "llmings.core.macos_statusbar.provider._KEY_FILE", key_file
        ):
            key = get_or_rotate_key()
        assert len(key) > 20

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        key_file = tmp_path / "nested" / "dir" / "statusbar.key"
        with patch(
            "llmings.core.macos_statusbar.provider._KEY_FILE", key_file
        ):
            key = get_or_rotate_key()
        assert key_file.exists()

    def test_stable_within_24h(self, tmp_path: Path) -> None:
        key_file = tmp_path / "statusbar.key"
        with patch(
            "llmings.core.macos_statusbar.provider._KEY_FILE", key_file
        ):
            key1 = get_or_rotate_key()
            key2 = get_or_rotate_key()
        assert key1 == key2


class TestStatusBar:
    def test_binary_path(self) -> None:
        assert _STATUSBAR_BIN.name == "HortStatusBar"
        assert _STATUSBAR_BIN.parent.name == "build"

    @patch("sys.platform", "darwin")
    @patch("subprocess.Popen")
    @patch("subprocess.run")
    @patch("llmings.core.macos_statusbar.provider.get_or_rotate_key", return_value="k")
    @patch("llmings.core.macos_statusbar.provider._STATUSBAR_BIN")
    def test_activate_launches_binary(
        self, mock_bin: MagicMock, _mock_key: MagicMock,
        mock_run: MagicMock, mock_popen: MagicMock,
    ) -> None:
        mock_bin.exists.return_value = True
        mock_bin.__str__ = lambda s: "/path/to/HortStatusBar"
        mock_run.return_value = MagicMock(stdout="")
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        plugin = _make_plugin()
        plugin.activate({})

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "--managed" in args

    @patch("sys.platform", "darwin")
    def test_activate_disabled_feature(self) -> None:
        plugin = _make_plugin(feature_enabled=False)
        plugin.activate({})
        assert plugin._process is None

    @patch("sys.platform", "linux")
    def test_activate_non_darwin(self) -> None:
        plugin = _make_plugin()
        plugin.activate({})
        assert plugin._process is None

    def test_get_status_not_running(self) -> None:
        plugin = _make_plugin()
        status = plugin.get_status()
        assert status["running"] is False
        assert status["pid"] is None

    def test_get_status_running(self) -> None:
        plugin = _make_plugin()
        mock_proc = MagicMock()
        mock_proc.pid = 999
        mock_proc.poll.return_value = None
        plugin._process = mock_proc

        status = plugin.get_status()
        assert status["running"] is True
        assert status["pid"] == 999

    def test_terminate_sends_sigterm(self) -> None:
        plugin = _make_plugin()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        plugin._process = mock_proc

        plugin.deactivate()

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
        assert plugin._process is None

    def test_terminate_sigkill_on_timeout(self) -> None:
        plugin = _make_plugin()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), 0]
        plugin._process = mock_proc

        plugin.deactivate()
        mock_proc.kill.assert_called_once()

    def test_terminate_already_exited(self) -> None:
        plugin = _make_plugin()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        plugin._process = mock_proc

        plugin.deactivate()
        assert plugin._process is None

    def test_terminate_no_process(self) -> None:
        plugin = _make_plugin()
        plugin.deactivate()

    @patch("subprocess.run")
    def test_find_existing_process(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="1234\n")
        plugin = _make_plugin()
        assert plugin._find_existing_process() is True

    @patch("subprocess.run")
    def test_find_existing_process_none(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")
        plugin = _make_plugin()
        assert plugin._find_existing_process() is False

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_find_existing_process_error(self, mock_run: MagicMock) -> None:
        plugin = _make_plugin()
        assert plugin._find_existing_process() is False


class TestVerifyEndpoint:
    @patch(
        "llmings.core.macos_statusbar.provider.get_or_rotate_key",
        return_value="correct-key",
    )
    def test_verify_rejects_wrong_key(self, _mock: MagicMock) -> None:
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()
        plugin = _make_plugin()
        app.include_router(plugin.get_router(), prefix="/api/llmings/macos-statusbar")
        client = TestClient(app)
        resp = client.post("/api/llmings/macos-statusbar/verify", headers={HEADER_NAME: "wrong"})
        assert resp.status_code == 403

    @patch(
        "llmings.core.macos_statusbar.provider.get_or_rotate_key",
        return_value="correct-key",
    )
    def test_verify_accepts_correct_key(self, _mock: MagicMock) -> None:
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()
        plugin = _make_plugin()
        app.include_router(plugin.get_router(), prefix="/api/llmings/macos-statusbar")
        client = TestClient(app)
        resp = client.post("/api/llmings/macos-statusbar/verify", headers={HEADER_NAME: "correct-key"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch(
        "llmings.core.macos_statusbar.provider.get_or_rotate_key",
        return_value="some-key",
    )
    def test_verify_rejects_missing_header(self, _mock: MagicMock) -> None:
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()
        plugin = _make_plugin()
        app.include_router(plugin.get_router(), prefix="/api/llmings/macos-statusbar")
        client = TestClient(app)
        resp = client.post("/api/llmings/macos-statusbar/verify")
        assert resp.status_code == 403

    def test_verify_timing_safe(self) -> None:
        import inspect
        from llmings.core.macos_statusbar import provider
        assert "compare_digest" in inspect.getsource(provider)


class TestSwiftBinary:
    def test_binary_exists(self) -> None:
        assert _STATUSBAR_BIN.exists(), f"Run: bash subprojects/macos_statusbar/build.sh"

    def test_binary_launches(self) -> None:
        proc = subprocess.Popen(
            [str(_STATUSBAR_BIN), "--managed"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        alive = proc.poll() is None
        proc.terminate()
        proc.wait(timeout=5)
        assert alive, "Binary exited immediately"
