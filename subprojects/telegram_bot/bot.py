"""Bot setup and lifecycle — creates the aiogram Dispatcher and runs polling."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from .acl import ACLMiddleware
from .config import BotConfig, load_config
from .handlers import router
from .hort_client import HortClient

logger = logging.getLogger(__name__)


def create_bot(config: BotConfig) -> tuple[Bot, Dispatcher, HortClient]:
    """Wire up the bot, dispatcher, ACL middleware, and hort client."""
    if not config.token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN not set. "
            "Add it to .env or export it as an environment variable."
        )

    # Allow overriding the Telegram API URL (for local test server)
    api_url = os.environ.get("TELEGRAM_API_URL", "")
    session = None
    if api_url:
        server = TelegramAPIServer.from_base(api_url)
        session = AiohttpSession()
        session.api = server
        logger.info("Using custom Telegram API: %s", api_url)

    bot = Bot(
        token=config.token,
        default=DefaultBotProperties(parse_mode=None),
        session=session,
    )

    dp = Dispatcher()

    # ACL middleware on both message and callback_query
    acl = ACLMiddleware(config)
    dp.message.middleware(acl)
    dp.callback_query.middleware(acl)

    # Include command handlers
    dp.include_router(router)

    # Hort client — injected into handler data
    hort_client = HortClient(config.hort.url)

    return bot, dp, hort_client


async def run_bot(config: BotConfig | None = None) -> None:
    """Main entry point — connect to hort, start polling Telegram."""
    if config is None:
        config = load_config()

    bot, dp, hort_client = create_bot(config)

    # Connect to hort
    logger.info("Connecting to hort at %s...", config.hort.url)
    try:
        await hort_client.connect()
        logger.info("Connected to hort.")
    except Exception:
        logger.exception("Failed to connect to hort — bot will start but commands will fail")

    # Inject hort_client into dispatcher workflow_data so handlers can access it
    dp.workflow_data["hort_client"] = hort_client

    try:
        logger.info("Starting Telegram bot polling...")
        await dp.start_polling(bot)
    finally:
        await hort_client.close()
        await bot.session.close()
