"""Standalone ping-pong bot for testing the real Telegram API.

Run:  python -m subprojects.telegram_bot.test_server

- Text → reversed
- Photo → black & white
- Sticker → replies with the sticker's emoji
- Location → replies with coordinates
- /ping → pong
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import BufferedInputFile, Message
from PIL import Image, ImageOps

# Load .env
_root = Path(__file__).resolve().parent.parent.parent
for line in (_root / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from .config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    await msg.answer(
        "Ping-pong test bot.\n\n"
        "Send text → reversed\n"
        "Send photo → black & white\n"
        "/ping → pong"
    )


@router.message(Command("ping"))
async def cmd_ping(msg: Message) -> None:
    await msg.answer("pong")


@router.message(F.photo)
async def on_photo(msg: Message, bot: Bot) -> None:
    photo = msg.photo[-1]  # largest resolution
    file = await bot.download(photo.file_id)
    assert file is not None

    img = Image.open(file)
    bw = ImageOps.grayscale(img)

    buf = io.BytesIO()
    bw.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    await msg.answer_photo(
        photo=BufferedInputFile(buf.read(), filename="bw.jpg"),
        caption="B&W",
    )


@router.message(F.sticker)
async def on_sticker(msg: Message) -> None:
    emoji = msg.sticker.emoji or "?"
    await msg.answer(f"Sticker emoji: {emoji}")


@router.message(F.location)
async def on_location(msg: Message) -> None:
    loc = msg.location
    await msg.answer(f"Lat: {loc.latitude}\nLon: {loc.longitude}")


@router.message(F.text)
async def on_text(msg: Message) -> None:
    text = msg.text or ""
    if text.startswith("/"):
        await msg.answer(f"Unknown command: {text}")
        return
    await msg.answer(text[::-1])


async def _run() -> None:
    config = load_config()
    if not config.token:
        print("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    bot = Bot(token=config.token, default=DefaultBotProperties(parse_mode=None))

    dp = Dispatcher()

    # ACL — only allowed users
    from .acl import ACLMiddleware
    acl = ACLMiddleware(config)
    dp.message.middleware(acl)
    dp.include_router(router)

    logger.info("Starting ping-pong bot (allowed: %s)...", config.allowed_users)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
