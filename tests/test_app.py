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
    _effective_max_width,
    _file_hash,
    _handle_ws_message,
    _parse_stream_config,
    _raise_window_for_config,
    _render_landing,
    _static_hash,
    get_observer_count,
    reset_observers,
)
from hort.models import ServerInfo, StreamConfig


class TestLandingPage:
    def test_returns_html(self, app_client: TestClient) -> None:
        with patch("hort.app.get_lan_ip", return_value="192.168.1.42"):
            resp = app_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "llming-control" in resp.text

    def test_contains_qr_code(self, app_client: TestClient) -> None:
        with patch("hort.app.get_lan_ip", return_value="192.168.1.42"):
            resp = app_client.get("/")
        assert "data:image/png;base64," in resp.text

    def test_contains_https_url(self, app_client: TestClient) -> None:
        with patch("hort.app.get_lan_ip", return_value="192.168.1.42"):
            resp = app_client.get("/")
        assert "https://192.168.1.42:8950" in resp.text


class TestRenderLanding:
    def test_renders(self) -> None:
        info = ServerInfo(lan_ip="10.0.0.1", http_port=8940, https_port=8950)
        html = _render_landing(info, "data:image/png;base64,abc123", "abc123hash0")
        assert "10.0.0.1" in html
        assert "data:image/png;base64,abc123" in html
        assert "<!DOCTYPE html>" in html
        assert "abc123hash0" in html


class TestWindowsEndpoint:
    def test_list_all(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/windows")
        assert resp.status_code == 200
        data = resp.json()
        assert "windows" in data
        assert "app_names" in data
        assert len(data["windows"]) == 3

    def test_filter_by_app(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/windows?app_filter=Chrome")
        assert resp.status_code == 200
        data = resp.json()
        for win in data["windows"]:
            assert "Chrome" in win["owner_name"]

    def test_app_names_sorted(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/windows")
        data = resp.json()
        assert data["app_names"] == sorted(data["app_names"])


class TestThumbnailEndpoint:
    def test_returns_jpeg(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/windows/101/thumbnail")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"

    def test_uncapturable_returns_placeholder(self, app_client: TestClient) -> None:
        with patch("hort.app.capture_window", return_value=None):
            resp = app_client.get("/api/windows/99999/thumbnail")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:4] == b"\x89PNG"


class TestSpacesEndpoints:
    def test_get_spaces(self, app_client: TestClient) -> None:
        with patch("hort.app.get_spaces", return_value=[]):
            resp = app_client.get("/api/spaces")
        assert resp.status_code == 200
        data = resp.json()
        assert "spaces" in data
        assert "count" in data
        assert "current" in data

    def test_switch_space(self, app_client: TestClient) -> None:
        with patch("hort.app.switch_to_space", return_value=True):
            resp = app_client.post("/api/spaces/2")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestStatusEndpoint:
    def test_returns_status(self, app_client: TestClient) -> None:
        resp = app_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "observers" in data
        assert "version" in data
        assert isinstance(data["observers"], int)

    def test_zero_observers_initially(self, app_client: TestClient) -> None:
        reset_observers()
        resp = app_client.get("/api/status")
        assert resp.json()["observers"] == 0


class TestObserverTracking:
    def test_observer_added_on_connect(self, app_client: TestClient) -> None:
        reset_observers()
        assert get_observer_count() == 0
        with app_client.websocket_connect("/ws/stream") as ws:
            ws.send_text(json.dumps({"window_id": 101, "fps": 60}))
            ws.receive_bytes()
            assert get_observer_count() == 1
        # After disconnect, observer is removed
        assert get_observer_count() == 0

    def test_multiple_observers(self, app_client: TestClient) -> None:
        reset_observers()
        with app_client.websocket_connect("/ws/stream") as ws1:
            ws1.send_text(json.dumps({"window_id": 101, "fps": 60}))
            ws1.receive_bytes()
            with app_client.websocket_connect("/ws/stream") as ws2:
                ws2.send_text(json.dumps({"window_id": 101, "fps": 60}))
                ws2.receive_bytes()
                assert get_observer_count() == 2
            assert get_observer_count() == 1
        assert get_observer_count() == 0

    def test_cleanup_on_error(self, app_client: TestClient) -> None:
        reset_observers()
        with patch("hort.app.capture_window", return_value=None):
            with app_client.websocket_connect("/ws/stream") as ws:
                ws.send_text(json.dumps({"window_id": 99999, "fps": 10}))
                ws.receive_text()  # error message
                assert get_observer_count() == 1
        assert get_observer_count() == 0


class TestWebSocket:
    def test_stream_receives_frames(self, app_client: TestClient) -> None:
        with app_client.websocket_connect("/ws/stream") as ws:
            config = {"window_id": 101, "fps": 10, "quality": 70, "max_width": 800}
            ws.send_text(json.dumps(config))
            data = ws.receive_bytes()
            assert data[:2] == b"\xff\xd8"  # JPEG magic

    def test_invalid_config(self, app_client: TestClient) -> None:
        with app_client.websocket_connect("/ws/stream") as ws:
            ws.send_text("not json")
            resp = ws.receive_text()
            parsed = json.loads(resp)
            assert "error" in parsed

    def test_capture_failure(self, app_client: TestClient) -> None:
        with patch("hort.app.capture_window", return_value=None):
            with app_client.websocket_connect("/ws/stream") as ws:
                config = {"window_id": 99999, "fps": 10}
                ws.send_text(json.dumps(config))
                resp = ws.receive_text()
                parsed = json.loads(resp)
                assert "error" in parsed

    def test_capture_failure_then_recover(
        self, app_client: TestClient, sample_jpeg_bytes: bytes
    ) -> None:
        """After capture failure, config resets; sending new config recovers."""
        call_count = 0

        def capture_side_effect(*args: object, **kwargs: object) -> bytes | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # First call fails
            return sample_jpeg_bytes  # Subsequent calls succeed

        with patch("hort.app.capture_window", side_effect=capture_side_effect):
            with app_client.websocket_connect("/ws/stream") as ws:
                ws.send_text(json.dumps({"window_id": 99999, "fps": 60}))
                # Get error from failed capture
                resp = ws.receive_text()
                assert "error" in json.loads(resp)
                # Server reset config to None, now send new valid config
                ws.send_text(json.dumps({"window_id": 101, "fps": 60}))
                # Should now get a frame
                data = ws.receive_bytes()
                assert data[:2] == b"\xff\xd8"

    def test_update_config_mid_stream(
        self, app_client: TestClient, sample_jpeg_bytes: bytes
    ) -> None:
        with patch("hort.app.capture_window", return_value=sample_jpeg_bytes):
            with app_client.websocket_connect("/ws/stream") as ws:
                ws.send_text(json.dumps({"window_id": 101, "fps": 10}))
                ws.receive_bytes()
                # Update config
                ws.send_text(json.dumps({"window_id": 102, "fps": 15, "quality": 90}))
                data = ws.receive_bytes()
                assert data[:2] == b"\xff\xd8"

    def test_stream_multiple_frames_no_config_update(
        self, app_client: TestClient, sample_jpeg_bytes: bytes
    ) -> None:
        """Covers the TimeoutError path when no config update arrives."""
        with patch("hort.app.capture_window", return_value=sample_jpeg_bytes):
            with app_client.websocket_connect("/ws/stream") as ws:
                ws.send_text(json.dumps({"window_id": 101, "fps": 60}))
                # Receive multiple frames without sending any config update
                for _ in range(3):
                    data = ws.receive_bytes()
                    assert data[:2] == b"\xff\xd8"


class TestEffectiveMaxWidth:
    def test_caps_to_client_resolution(self) -> None:
        config = StreamConfig(
            window_id=1, max_width=3840, screen_width=390, screen_dpr=3.0
        )
        assert _effective_max_width(config) == 1170  # 390 * 3

    def test_uses_max_width_when_smaller(self) -> None:
        config = StreamConfig(
            window_id=1, max_width=800, screen_width=1920, screen_dpr=1.0
        )
        assert _effective_max_width(config) == 800

    def test_no_screen_info_uses_max_width(self) -> None:
        config = StreamConfig(window_id=1, max_width=1200)
        assert _effective_max_width(config) == 1200

    def test_tablet_resolution(self) -> None:
        config = StreamConfig(
            window_id=1, max_width=5140, screen_width=1024, screen_dpr=2.0
        )
        assert _effective_max_width(config) == 2048


class TestViewerPage:
    def test_returns_html(self, app_client: TestClient) -> None:
        resp = app_client.get("/viewer")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "llming-control" in resp.text

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
            patch("hort.app.capture_window", return_value=sample_jpeg_bytes),
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
            patch("hort.app.capture_window", return_value=sample_jpeg_bytes),
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
            patch("hort.app.capture_window", return_value=sample_jpeg_bytes),
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


class TestRaiseWindowForConfig:
    def test_raises_when_window_found(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        config = StreamConfig(window_id=101)
        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.app._activate_app") as mock_activate,
        ):
            _raise_window_for_config(config)
        mock_activate.assert_called_once()
        assert mock_activate.call_args[0][0] == 1001  # Chrome's PID
        assert mock_activate.call_args[1]["bounds"] is not None

    def test_switches_space_when_needed(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        config = StreamConfig(window_id=101)
        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.windows._get_space_index_map", return_value={}),
            patch("hort.windows._get_window_space", return_value=2),
            patch("hort.app._activate_app"),
            patch("hort.spaces.get_current_space_index", return_value=1),
            patch("hort.spaces.switch_to_space") as mock_switch,
        ):
            _raise_window_for_config(config)
        mock_switch.assert_called_once_with(2)

    def test_noop_when_window_not_found(self) -> None:
        config = StreamConfig(window_id=99999)
        with (
            patch("hort.windows._raw_window_list", return_value=[]),
            patch("hort.windows._get_space_index_map", return_value={}),
            patch("hort.windows._get_window_space", return_value=0),
            patch("hort.app._activate_app") as mock_activate,
        ):
            _raise_window_for_config(config)
        mock_activate.assert_not_called()


class TestHandleWsMessage:
    def test_config_update(self) -> None:
        config = StreamConfig(window_id=1)
        result = _handle_ws_message('{"window_id": 2, "fps": 15}', config)
        assert result is not None
        assert result.window_id == 2

    def test_config_update_same_window(self) -> None:
        config = StreamConfig(window_id=1)
        result = _handle_ws_message('{"window_id": 1, "fps": 30}', config)
        assert result is not None
        assert result.fps == 30

    def test_input_event_click(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        config = StreamConfig(window_id=101)
        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.app.handle_input") as mock_input,
        ):
            result = _handle_ws_message(
                '{"type": "click", "nx": 0.5, "ny": 0.5}', config
            )
        assert result is None
        mock_input.assert_called_once()

    def test_input_event_key(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        config = StreamConfig(window_id=101)
        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.app.handle_input") as mock_input,
        ):
            result = _handle_ws_message(
                '{"type": "key", "key": "a", "modifiers": []}', config
            )
        assert result is None
        mock_input.assert_called_once()

    def test_input_event_scroll(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        config = StreamConfig(window_id=101)
        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.app.handle_input") as mock_input,
        ):
            result = _handle_ws_message(
                '{"type": "scroll", "nx": 0.5, "ny": 0.5, "dx": 0, "dy": -3}', config
            )
        assert result is None
        mock_input.assert_called_once()

    def test_input_window_not_found(self) -> None:
        config = StreamConfig(window_id=99999)
        with (
            patch("hort.windows._raw_window_list", return_value=[]),
            patch("hort.windows._get_space_index_map", return_value={}),
            patch("hort.windows._get_window_space", return_value=0),
            patch("hort.app.handle_input") as mock_input,
        ):
            result = _handle_ws_message(
                '{"type": "click", "nx": 0.5, "ny": 0.5}', config
            )
        assert result is None
        mock_input.assert_not_called()

    def test_invalid_json(self) -> None:
        config = StreamConfig(window_id=1)
        result = _handle_ws_message("not json", config)
        assert result is None

    def test_invalid_input_event(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        config = StreamConfig(window_id=101)
        with (
            patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
            patch("hort.windows._get_space_index_map", return_value={1: 1}),
            patch("hort.windows._get_window_space", return_value=1),
            patch("hort.app.handle_input") as mock_input,
        ):
            # nx out of range triggers ValidationError
            result = _handle_ws_message(
                '{"type": "click", "nx": 5.0, "ny": 0.5}', config
            )
        assert result is None
        mock_input.assert_not_called()


class TestParseStreamConfig:
    def test_valid(self) -> None:
        raw = '{"window_id": 42, "fps": 15}'
        config = _parse_stream_config(raw)
        assert config is not None
        assert config.window_id == 42
        assert config.fps == 15

    def test_invalid_json(self) -> None:
        assert _parse_stream_config("not json") is None

    def test_validation_error(self) -> None:
        assert _parse_stream_config('{"window_id": 1, "fps": 0}') is None

    def test_missing_required(self) -> None:
        assert _parse_stream_config('{"fps": 10}') is None

    def test_defaults(self) -> None:
        config = _parse_stream_config('{"window_id": 1}')
        assert config is not None
        assert config.fps == 10
        assert config.quality == 70
        assert config.max_width == 800

    def test_screen_info(self) -> None:
        config = _parse_stream_config(
            '{"window_id": 1, "screen_width": 1024, "screen_dpr": 2.0}'
        )
        assert config is not None
        assert config.screen_width == 1024
        assert config.screen_dpr == 2.0
