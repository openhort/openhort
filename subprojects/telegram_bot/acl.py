"""Access control middleware — rejects messages from unauthorized users."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update

from .config import BotConfig

logger = logging.getLogger(__name__)


class ACLMiddleware(BaseMiddleware):
    """Drops all updates from users not in the allow list.

    Silently ignores unauthorized users — no error message is sent
    to avoid revealing the bot's existence to strangers.
    """

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None:
            logger.warning("ACL: update with no from_user, dropping")
            return None

        if not self.config.is_user_allowed(user.username):
            logger.warning(
                "ACL: rejected user_id=%s username=%s",
                user.id,
                user.username,
            )
            return None

        return await handler(event, data)
