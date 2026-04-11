"""Tests for FastAPI application routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hort.app import (
    _dev_reload_script,
    _file_hash,
    _render_landing,
    _static_hash,
)
from hort.models import ServerInfo


class TestRootPage:
    def test_root_serves_viewer(self, app_client: TestClient) -> None:
        resp = app_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "hort" in resp.text

    def test_root_same_as_viewer(self, app_client: TestClient) -> None:
        root = app_client.get("/")
        viewer = app_client.get("/viewer")
        assert root.status_code == viewer.status_code


class TestRenderLanding:
    def test_renders(self) -> None:
        info = ServerInfo(lan_ip="10.0.0.1", http_port=8940, https_port=8950)
        html = _render_landing(info, "data:image/png;base64,abc123", "abc123hash0")
        assert "10.0.0.1" in html
        assert "data:image/png;base64,abc123" in html
        assert "<!DOCTYPE html>" in html
        assert "abc123hash0" in html


class TestViewerPage:
    def test_returns_html(self, app_client: TestClient) -> None:
        resp = app_client.get("/viewer")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_has_etag(self, app_client: TestClient) -> None:
        resp = app_client.get("/viewer")
        assert "etag" in resp.headers
        assert len(resp.headers["etag"]) == 12

    def test_no_dev_script_by_default(self, app_client: TestClient) -> None:
        resp = app_client.get("/viewer")
        assert "/ws/devreload" not in resp.text


class TestViewerDevMode:
    def test_dev_script_injected(
        self, sample_raw_windows: list[dict[str, Any]], sample_jpeg_bytes: bytes
    ) -> None:
        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.screen._raw_capture", return_value=None),
        ):
            from hort.app import create_app as _create

            dev_app = _create(dev_mode=True)
            with TestClient(dev_app) as client:
                resp = client.get("/viewer")
        assert "/ws/devreload" in resp.text


class TestManifest:
    def test_returns_json(self, app_client: TestClient) -> None:
        resp = app_client.get("/manifest.json")
        assert resp.status_code == 200
        assert "application/manifest+json" in resp.headers["content-type"]
        data = resp.json()
        assert data["short_name"] == "hort"
        assert data["display"] == "fullscreen"
        assert len(data["icons"]) == 2


class TestAppIcon:
    def test_returns_png(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/icon/192")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:4] == b"\x89PNG"

    def test_different_sizes(self, app_client: TestClient) -> None:
        r1 = app_client.get("/api/icon/64")
        r2 = app_client.get("/api/icon/512")
        assert len(r1.content) < len(r2.content)


class TestServiceWorker:
    def test_returns_js(self, app_client: TestClient) -> None:
        resp = app_client.get("/sw.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]
        assert "fetch" in resp.text


class TestHashEndpoint:
    def test_returns_hash(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/hash")
        assert resp.status_code == 200
        data = resp.json()
        assert "hash" in data
        assert len(data["hash"]) == 12


class TestFileHash:
    def test_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h = _file_hash(f)
        assert len(h) == 12

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / "nope.txt"
        assert _file_hash(f) == "0"

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h1 = _file_hash(f)
        f.write_text("world")
        h2 = _file_hash(f)
        assert h1 != h2


class TestStaticHash:
    def test_returns_string(self) -> None:
        h = _static_hash()
        assert isinstance(h, str)
        assert len(h) == 12


class TestDevReloadScript:
    def test_contains_websocket(self) -> None:
        script = _dev_reload_script()
        assert "/ws/devreload" in script
        assert "<script>" in script


class TestDevReloadWebSocket:
    def test_connect_and_disconnect(
        self, sample_raw_windows: list[dict[str, Any]], sample_jpeg_bytes: bytes
    ) -> None:
        """Covers the WebSocketDisconnect path in dev_reload."""

        async def sleep_then_raise(*args: object) -> None:
            raise WebSocketDisconnect()

        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.screen._raw_capture", return_value=None),
            patch("hort.app.asyncio.sleep", side_effect=sleep_then_raise),
        ):
            from hort.app import create_app as _create

            test_app = _create(dev_mode=True)
            with TestClient(test_app) as client:
                with client.websocket_connect("/ws/devreload"):
                    pass

    def test_sends_reload_on_hash_change(
        self, sample_raw_windows: list[dict[str, Any]], sample_jpeg_bytes: bytes
    ) -> None:
        call_count = 0

        def changing_hash() -> str:
            nonlocal call_count
            call_count += 1
            return f"hash{call_count:06d}"

        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.screen._raw_capture", return_value=None),
            patch("hort.app._static_hash", side_effect=changing_hash),
            patch("hort.app.asyncio.sleep", return_value=None),
        ):
            from hort.app import create_app as _create

            test_app = _create(dev_mode=True)
            with TestClient(test_app) as client:
                with client.websocket_connect("/ws/devreload") as ws:
                    msg = ws.receive_text()
                    data = json.loads(msg)
                    assert data["type"] == "reload"
                    assert "hash" in data


# ===== Session-based endpoint tests =====


class TestConnectorsEndpoint:
    def test_returns_connectors(self, app_client: TestClient) -> None:
        with patch("hort.app.get_lan_ip", return_value="192.168.1.42"):
            resp = app_client.get("/api/connectors")
        assert resp.status_code == 200
        data = resp.json()
        assert "lan" in data
        assert "cloud" in data
        assert data["lan"]["active"] is True
        assert data["lan"]["ip"] == "192.168.1.42"


class TestCloudTokenEndpoint:
    def test_create_temporary_token(self, app_client: TestClient, tmp_path: Path) -> None:
        app_client.app.state.cloud_tokens = {}  # type: ignore[union-attr]
        with patch("hort.access.tokens.TokenStore") as MockStore, \
             patch("hort.app._TEMP_TOKEN_FILE", tmp_path / "temp-token"):
            inst = MockStore.return_value
            inst.revoke_all_temporary.return_value = 0
            inst.create_temporary.return_value = "temp-tok-123"
            resp = app_client.post(
                "/api/connectors/cloud/token",
                json={"permanent": False},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["token"] == "temp-tok-123"
        assert data["permanent"] is False

    def test_create_permanent_token(self, app_client: TestClient) -> None:
        app_client.app.state.cloud_tokens = {}  # type: ignore[union-attr]
        with patch("hort.access.tokens.TokenStore") as MockStore:
            inst = MockStore.return_value
            inst.create_permanent.return_value = "perm-tok-456"
            resp = app_client.post(
                "/api/connectors/cloud/token",
                json={"permanent": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["token"] == "perm-tok-456"
        assert data["permanent"] is True


class TestCloudQrEndpoint:
    def test_generate_qr(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/qr?url=https://example.com/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["qr"].startswith("data:image/png;base64,")

    def test_empty_url(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/qr")
        assert resp.status_code == 200
        data = resp.json()
        assert data["qr"] == ""


class TestSessionEndpoint:
    def test_create_session(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        resp = app_client.post("/api/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert len(data["session_id"]) > 10

    def test_create_multiple_sessions(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        r1 = app_client.post("/api/session").json()
        r2 = app_client.post("/api/session").json()
        assert r1["session_id"] != r2["session_id"]


class TestControlWebSocket:
    def test_connect_and_receive_connected(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with app_client.websocket_connect(f"/ws/control/{sid}") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connected"
            assert msg["version"] == "0.1.0"

    def test_invalid_session(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        try:
            with app_client.websocket_connect("/ws/control/nonexistent"):
                pass
        except Exception:
            pass  # llming-com closes with 4004, TestClient raises

    def test_list_windows(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with app_client.websocket_connect(f"/ws/control/{sid}") as ws:
            ws.receive_text()  # connected message
            ws.send_text(json.dumps({"type": "list_windows"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "windows_list"
            assert "windows" in msg
            assert "app_names" in msg

    def test_get_status(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with app_client.websocket_connect(f"/ws/control/{sid}") as ws:
            ws.receive_text()  # connected
            ws.send_text(json.dumps({"type": "get_status"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "status"
            assert "observers" in msg

    def test_heartbeat(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with app_client.websocket_connect(f"/ws/control/{sid}") as ws:
            ws.receive_text()  # connected
            ws.send_text(json.dumps({"type": "heartbeat"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "heartbeat_ack"


class TestTargetDiscovery:
    def test_register_targets_on_create(self, app_client: TestClient) -> None:
        """create_app registers the local macOS target."""
        from hort.targets import TargetRegistry

        reg = TargetRegistry.get()
        targets = reg.list_targets()
        assert any(t.id == "local-macos" for t in targets)

    def test_list_targets_via_ws(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with app_client.websocket_connect(f"/ws/control/{sid}") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "list_targets"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "targets_list"
            assert len(msg["targets"]) >= 1

    def test_get_spaces_via_ws(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with app_client.websocket_connect(f"/ws/control/{sid}") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "get_spaces"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "spaces"

    def test_get_thumbnail_via_ws(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with app_client.websocket_connect(f"/ws/control/{sid}") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "get_thumbnail", "window_id": 101}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "thumbnail"

    def test_switch_space_via_ws(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        sid = app_client.post("/api/session").json()["session_id"]
        with (
            patch("hort.spaces.switch_to_space", return_value=True),
            app_client.websocket_connect(f"/ws/control/{sid}") as ws,
        ):
            ws.receive_text()
            ws.send_text(json.dumps({"type": "switch_space", "index": 1}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "space_switched"

    def test_register_targets_import_error(self) -> None:
        """Covers the except ImportError branch in _register_targets."""
        from hort.app import _register_targets
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        with (
            patch(
                "llmings.core.macos_windows.provider.MacOSWindowsExtension",
                side_effect=ImportError("no quartz"),
            ),
            patch("hort.app._refresh_docker_targets"),
        ):
            _register_targets()
        # Should not raise

    def test_register_docker_no_docker(self) -> None:
        from hort.app import _refresh_docker_targets
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        reg = TargetRegistry.get()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            _refresh_docker_targets()
        assert reg.list_targets() == []

    def test_register_docker_bad_returncode(self) -> None:
        from hort.app import _refresh_docker_targets
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        mock_result = type("R", (), {"returncode": 1, "stdout": ""})()
        with patch("subprocess.run", return_value=mock_result):
            _refresh_docker_targets()
        assert TargetRegistry.get().list_targets() == []

    def test_register_docker_removes_stopped(self) -> None:
        from hort.app import _refresh_docker_targets
        from hort.targets import TargetInfo, TargetRegistry
        from tests.test_targets import StubProvider

        TargetRegistry.reset()
        reg = TargetRegistry.get()
        reg.register("docker-old", TargetInfo(id="docker-old", name="Old", provider_type="linux-docker"), StubProvider())
        mock_result = type("R", (), {"returncode": 0, "stdout": ""})()
        with patch("subprocess.run", return_value=mock_result):
            _refresh_docker_targets()
        assert reg.get_provider("docker-old") is None

    def test_register_docker_empty(self) -> None:
        from hort.app import _refresh_docker_targets
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        reg = TargetRegistry.get()
        mock_result = type("R", (), {"returncode": 0, "stdout": ""})()
        with patch("subprocess.run", return_value=mock_result):
            _refresh_docker_targets()
        assert reg.list_targets() == []

    def test_register_docker_with_empty_name_in_list(self) -> None:
        from hort.app import _refresh_docker_targets
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        reg = TargetRegistry.get()
        # "a\n\nb" → strip().splitlines() = ['a', '', 'b'] — empty string in middle
        mock_result = type("R", (), {"returncode": 0, "stdout": "c1\n\nc2"})()
        with (
            patch("subprocess.run", return_value=mock_result),
            patch(
                "llmings.core.linux_windows.provider.LinuxWindowsExtension",
                side_effect=ImportError("no docker"),
            ),
        ):
            _refresh_docker_targets()
        assert reg.list_targets() == []

    def test_register_docker_with_container(self) -> None:
        from hort.app import _refresh_docker_targets
        from hort.targets import TargetRegistry

        TargetRegistry.reset()
        reg = TargetRegistry.get()
        mock_result = type("R", (), {"returncode": 0, "stdout": "openhort-linux-desktop\n"})()
        with patch("subprocess.run", return_value=mock_result):
            _refresh_docker_targets()
        targets = reg.list_targets()
        assert len(targets) == 1
        assert targets[0].provider_type == "linux-docker"


class TestTerminalWebSocket:
    def test_invalid_terminal(self, app_client: TestClient) -> None:
        try:
            with app_client.websocket_connect("/ws/terminal/nonexistent"):
                pass
        except Exception:
            pass  # Server closes with 4004


class TestStreamWebSocket:
    def test_invalid_session(self, app_client: TestClient) -> None:
        from hort.session import HortRegistry

        HortRegistry.reset()
        try:
            with app_client.websocket_connect("/ws/stream/nonexistent"):
                pass
        except Exception:
            pass  # Server closes with 4004, TestClient raises
