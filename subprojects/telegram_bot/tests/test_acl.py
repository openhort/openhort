"""Tests for ACL middleware — verifies unauthorized users are blocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from subprojects.telegram_bot.acl import ACLMiddleware
from subprojects.telegram_bot.config import BotConfig


def _make_message(username: str | None = None, user_id: int = 12345) -> MagicMock:
    """Create a mock Message with a from_user."""
    msg = MagicMock()
    if username is None and user_id == 0:
        msg.from_user = None
    else:
        msg.from_user = MagicMock()
        msg.from_user.username = username
        msg.from_user.id = user_id
    return msg


@pytest.fixture
def config() -> BotConfig:
    return BotConfig(allowed_users=["alice_dev"])


@pytest.fixture
def middleware(config: BotConfig) -> ACLMiddleware:
    return ACLMiddleware(config)


class TestACLMiddleware:
    @pytest.mark.asyncio
    async def test_allowed_user_passes(self, middleware: ACLMiddleware) -> None:
        handler = AsyncMock(return_value="ok")
        msg = _make_message(username="alice_dev")
        result = await middleware(handler, msg, {})
        handler.assert_called_once_with(msg, {})
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_rejected_user_blocked(self, middleware: ACLMiddleware) -> None:
        handler = AsyncMock()
        msg = _make_message(username="hacker")
        result = await middleware(handler, msg, {})
        handler.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_username_blocked(self, middleware: ACLMiddleware) -> None:
        handler = AsyncMock()
        msg = _make_message(username=None)
        result = await middleware(handler, msg, {})
        handler.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_from_user_blocked(self, middleware: ACLMiddleware) -> None:
        handler = AsyncMock()
        msg = _make_message(username=None, user_id=0)
        result = await middleware(handler, msg, {})
        handler.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_allowed_users(self) -> None:
        config = BotConfig(allowed_users=["alice", "alice_dev"])
        mw = ACLMiddleware(config)
        handler = AsyncMock(return_value="ok")

        msg_alice = _make_message(username="alice")
        assert await mw(handler, msg_alice, {}) == "ok"

        msg_mik = _make_message(username="alice_dev")
        assert await mw(handler, msg_mik, {}) == "ok"

        handler_reject = AsyncMock()
        msg_eve = _make_message(username="eve")
        assert await mw(handler_reject, msg_eve, {}) is None
        handler_reject.assert_not_called()
