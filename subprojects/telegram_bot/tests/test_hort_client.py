"""Tests for the hort WebSocket client."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestServer

from subprojects.telegram_bot.hort_client import HortClient


@pytest.fixture
def fake_hort_app() -> web.Application:
    """Create a minimal fake hort server for testing the client."""
    app = web.Application()

    async def create_session(request: web.Request) -> web.Response:
        return web.json_response({"session_id": "test-session", "is_local": True})

    async def control_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Send connected message
        await ws.send_json({"type": "connected", "version": "0.1.0"})

        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                req_id = data.get("_req_id")
                msg_type = data.get("type")

                if msg_type == "list_targets":
                    await ws.send_json(
                        {
                            "type": "targets_list",
                            "_req_id": req_id,
                            "targets": [
                                {
                                    "id": "local-macos",
                                    "name": "This Mac",
                                    "provider_type": "macos",
                                    "status": "online",
                                }
                            ],
                            "active": "all",
                        }
                    )
                elif msg_type == "list_windows":
                    await ws.send_json(
                        {
                            "type": "windows_list",
                            "_req_id": req_id,
                            "windows": [
                                {
                                    "window_id": 42,
                                    "owner_name": "Finder",
                                    "window_name": "Documents",
                                    "bounds": {
                                        "x": 0,
                                        "y": 0,
                                        "width": 800,
                                        "height": 600,
                                    },
                                    "target_id": "local-macos",
                                }
                            ],
                            "app_names": ["Finder"],
                        }
                    )
                elif msg_type == "get_thumbnail":
                    # 1x1 white JPEG
                    fake_jpeg = base64.b64encode(
                        bytes(
                            [
                                0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
                                0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
                                0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
                            ]
                        )
                    ).decode()
                    await ws.send_json(
                        {
                            "type": "thumbnail",
                            "_req_id": req_id,
                            "window_id": data.get("window_id"),
                            "data": fake_jpeg,
                        }
                    )
                elif msg_type == "get_status":
                    await ws.send_json(
                        {
                            "type": "status",
                            "_req_id": req_id,
                            "observers": 1,
                            "version": "0.1.0",
                        }
                    )
                elif msg_type == "get_spaces":
                    await ws.send_json(
                        {
                            "type": "spaces",
                            "_req_id": req_id,
                            "spaces": [
                                {"index": 1, "is_current": True},
                                {"index": 2, "is_current": False},
                            ],
                            "current": 1,
                            "count": 2,
                        }
                    )
                elif msg_type == "switch_space":
                    await ws.send_json(
                        {
                            "type": "space_switched",
                            "_req_id": req_id,
                            "ok": True,
                            "target": data.get("index"),
                        }
                    )
                elif msg_type == "set_target":
                    await ws.send_json(
                        {
                            "type": "target_changed",
                            "_req_id": req_id,
                            "target_id": data.get("target_id"),
                        }
                    )
                elif msg_type == "heartbeat":
                    await ws.send_json({"type": "heartbeat_ack"})
            elif msg.type == web.WSMsgType.ERROR:
                break

        return ws

    app.router.add_post("/api/session", create_session)
    app.router.add_get("/ws/control/{session_id}", control_ws)
    return app


@pytest.fixture
async def hort_server(fake_hort_app: web.Application) -> TestServer:
    server = TestServer(fake_hort_app)
    await server.start_server()
    yield server
    await server.close()


@pytest.fixture
async def client(hort_server: TestServer) -> HortClient:
    url = f"http://localhost:{hort_server.port}"
    c = HortClient(url, timeout=5.0)
    await c.connect()
    yield c
    await c.close()


class TestHortClient:
    @pytest.mark.asyncio
    async def test_connect(self, client: HortClient) -> None:
        assert client.connected

    @pytest.mark.asyncio
    async def test_list_targets(self, client: HortClient) -> None:
        targets = await client.list_targets()
        assert len(targets) == 1
        assert targets[0]["id"] == "local-macos"
        assert targets[0]["status"] == "online"

    @pytest.mark.asyncio
    async def test_list_windows(self, client: HortClient) -> None:
        windows = await client.list_windows()
        assert len(windows) == 1
        assert windows[0]["owner_name"] == "Finder"
        assert windows[0]["window_id"] == 42

    @pytest.mark.asyncio
    async def test_list_windows_with_filter(self, client: HortClient) -> None:
        windows = await client.list_windows(app_filter="Finder")
        assert len(windows) == 1

    @pytest.mark.asyncio
    async def test_get_thumbnail(self, client: HortClient) -> None:
        jpeg = await client.get_thumbnail(42, target_id="local-macos")
        assert jpeg is not None
        assert isinstance(jpeg, bytes)
        # JPEG magic bytes
        assert jpeg[:2] == b"\xff\xd8"

    @pytest.mark.asyncio
    async def test_get_status(self, client: HortClient) -> None:
        status = await client.get_status()
        assert status["observers"] == 1
        assert status["version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_get_spaces(self, client: HortClient) -> None:
        data = await client.get_spaces()
        assert len(data["spaces"]) == 2
        assert data["current"] == 1

    @pytest.mark.asyncio
    async def test_switch_space(self, client: HortClient) -> None:
        result = await client.switch_space(2)
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_set_target(self, client: HortClient) -> None:
        result = await client.set_target("local-macos")
        assert result["target_id"] == "local-macos"

    @pytest.mark.asyncio
    async def test_close(self, hort_server: TestServer) -> None:
        url = f"http://localhost:{hort_server.port}"
        c = HortClient(url, timeout=5.0)
        await c.connect()
        assert c.connected
        await c.close()
        assert not c.connected
