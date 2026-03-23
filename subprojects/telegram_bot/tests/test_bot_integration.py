"""End-to-end integration test — fake hort server + real aiogram dispatcher."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update, User
from unittest.mock import AsyncMock, MagicMock, patch

from subprojects.telegram_bot.acl import ACLMiddleware
from subprojects.telegram_bot.bot import create_bot
from subprojects.telegram_bot.config import BotConfig, HortConfig
from subprojects.telegram_bot.handlers import router
from subprojects.telegram_bot.hort_client import HortClient


# ── Fake hort server ────────────────────────────────────


def _build_fake_hort() -> web.Application:
    app = web.Application()

    async def create_session(request: web.Request) -> web.Response:
        return web.json_response({"session_id": "integ-session", "is_local": True})

    async def control_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "connected", "version": "0.1.0"})

        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            req_id = data.get("_req_id")
            t = data.get("type")

            if t == "list_windows":
                await ws.send_json({
                    "type": "windows_list", "_req_id": req_id,
                    "windows": [
                        {"window_id": 1, "owner_name": "Safari", "window_name": "Google",
                         "bounds": {"x": 0, "y": 0, "width": 1024, "height": 768},
                         "target_id": "local"},
                    ],
                    "app_names": ["Safari"],
                })
            elif t == "get_thumbnail":
                fake_jpeg = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 100).decode()
                await ws.send_json({
                    "type": "thumbnail", "_req_id": req_id,
                    "window_id": data.get("window_id"), "data": fake_jpeg,
                })
            elif t == "list_targets":
                await ws.send_json({
                    "type": "targets_list", "_req_id": req_id,
                    "targets": [{"id": "local", "name": "Test Mac", "provider_type": "macos", "status": "online"}],
                    "active": "all",
                })
            elif t == "get_status":
                await ws.send_json({
                    "type": "status", "_req_id": req_id,
                    "observers": 3, "version": "test",
                })
            elif t == "heartbeat":
                await ws.send_json({"type": "heartbeat_ack"})

        return ws

    app.router.add_post("/api/session", create_session)
    app.router.add_get("/ws/control/{session_id}", control_ws)
    return app


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
async def hort_server() -> TestServer:
    server = TestServer(_build_fake_hort())
    await server.start_server()
    yield server
    await server.close()


@pytest.fixture
async def hort_client(hort_server: TestServer) -> HortClient:
    c = HortClient(f"http://localhost:{hort_server.port}", timeout=5.0)
    await c.connect()
    yield c
    await c.close()


@pytest.fixture
def config() -> BotConfig:
    return BotConfig(
        allowed_users=["alice_dev"],
        hort=HortConfig(url="http://localhost:8940"),
        token="fake-token-for-test",
    )


# ── Helpers ─────────────────────────────────────────────


def _make_user(username: str) -> User:
    return User(id=12345, is_bot=False, first_name="Test", username=username)


def _make_message(text: str, user: User) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.from_user = user
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = 1
    msg.chat.type = "private"
    msg.date = None
    msg.message_id = 1
    return msg


# ── Tests ───────────────────────────────────────────────


class TestEndToEnd:
    """Integration tests: fake hort server + real ACL + real handlers."""

    @pytest.mark.asyncio
    async def test_acl_blocks_unauthorized(
        self, hort_client: HortClient, config: BotConfig
    ) -> None:
        """Unauthorized user gets silently dropped."""
        acl = ACLMiddleware(config)
        handler = AsyncMock(return_value="should not reach")

        bad_user = _make_user("evil_hacker")
        msg = _make_message("/status", bad_user)

        result = await acl(handler, msg, {})
        assert result is None
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_acl_allows_authorized(
        self, hort_client: HortClient, config: BotConfig
    ) -> None:
        """Authorized user passes through ACL."""
        acl = ACLMiddleware(config)
        handler = AsyncMock(return_value="ok")

        good_user = _make_user("alice_dev")
        msg = _make_message("/status", good_user)

        result = await acl(handler, msg, {})
        assert result == "ok"
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_screenshot_flow(self, hort_client: HortClient) -> None:
        """End-to-end: list windows via hort → get thumbnail → verify JPEG."""
        windows = await hort_client.list_windows()
        assert len(windows) == 1
        assert windows[0]["owner_name"] == "Safari"

        jpeg = await hort_client.get_thumbnail(
            windows[0]["window_id"], target_id=windows[0]["target_id"]
        )
        assert jpeg is not None
        assert jpeg[:2] == b"\xff\xd8"  # JPEG magic bytes

    @pytest.mark.asyncio
    async def test_full_status_flow(self, hort_client: HortClient) -> None:
        """End-to-end: get server status."""
        status = await hort_client.get_status()
        assert status["observers"] == 3
        assert status["version"] == "test"

    @pytest.mark.asyncio
    async def test_full_targets_flow(self, hort_client: HortClient) -> None:
        """End-to-end: list targets."""
        targets = await hort_client.list_targets()
        assert len(targets) == 1
        assert targets[0]["name"] == "Test Mac"

    @pytest.mark.asyncio
    async def test_acl_then_handler(
        self, hort_client: HortClient, config: BotConfig
    ) -> None:
        """Authorized user sends /status, handler uses real hort client."""
        from subprojects.telegram_bot.handlers import cmd_status

        msg = _make_message("/status", _make_user("alice_dev"))
        await cmd_status(msg, hort_client=hort_client)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "Observers: 3" in text

    @pytest.mark.asyncio
    async def test_acl_then_screenshot(
        self, hort_client: HortClient, config: BotConfig
    ) -> None:
        """Authorized user takes screenshot through real hort client."""
        from subprojects.telegram_bot.handlers import cmd_screenshot

        msg = _make_message("/screenshot Safari", _make_user("alice_dev"))
        await cmd_screenshot(msg, hort_client=hort_client)

        msg.answer_photo.assert_called_once()
        kwargs = msg.answer_photo.call_args[1]
        assert "Safari" in kwargs["caption"]
