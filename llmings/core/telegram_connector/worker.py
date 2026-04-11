"""Telegram polling worker — thin subprocess.

Does transport only:
- Connects to Telegram API via aiogram
- Receives messages and callbacks
- Forwards them as raw JSON to the main process via IPC
- Main sends back responses, worker delivers them via Telegram bot API

No ACL, no command routing, no chat backend — all in main.
"""

from __future__ import annotations

import asyncio
import logging
import os

from hort.lifecycle.worker import Worker

logger = logging.getLogger(__name__)


class TelegramWorker(Worker):
    name = "telegram"
    protocol_version = 1

    def __init__(self) -> None:
        super().__init__()
        self._bot = None
        self._dp = None
        self._polling_task: asyncio.Task | None = None
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    async def on_connected(self) -> None:
        """Start Telegram polling after IPC is ready."""
        if not self._token:
            logger.error("TELEGRAM_BOT_TOKEN not set")
            return

        if self._polling_task and not self._polling_task.done():
            return  # already polling

        self._polling_task = asyncio.create_task(self._start_polling())

    async def on_message(self, msg: dict) -> None:
        """Handle messages from main (send responses to Telegram)."""
        if msg.get("type") == "send_message":
            await self._send_telegram(
                chat_id=msg["chat_id"],
                text=msg.get("text", ""),
                parse_mode=msg.get("parse_mode"),
                reply_markup=msg.get("reply_markup"),
            )
        elif msg.get("type") == "send_photo":
            await self._send_photo(
                chat_id=msg["chat_id"],
                photo=msg.get("photo", ""),
                caption=msg.get("caption", ""),
            )

    async def on_disconnected(self) -> None:
        """Main disconnected — keep polling, buffer messages."""
        logger.info("Main disconnected — buffering messages")

    async def _start_polling(self) -> None:
        from aiogram import Bot, Dispatcher
        from aiogram.types import Message, CallbackQuery

        bot = Bot(token=self._token)
        dp = Dispatcher()
        self._bot = bot
        self._dp = dp

        worker = self

        @dp.message()
        async def on_message(message: Message) -> None:
            if not message.from_user:
                return
            data = {
                "type": "telegram_message",
                "chat_id": str(message.chat.id),
                "user_id": str(message.from_user.id),
                "username": message.from_user.username or "",
                "text": message.text or "",
                "message_id": message.message_id,
            }
            try:
                await worker.send(data)
            except ConnectionError:
                logger.warning("IPC not connected, dropping message from @%s", message.from_user.username)

        @dp.callback_query()
        async def on_callback(callback: CallbackQuery) -> None:
            if not callback.from_user or not callback.data:
                return
            data = {
                "type": "telegram_callback",
                "chat_id": str(callback.message.chat.id) if callback.message else "",
                "user_id": str(callback.from_user.id),
                "username": callback.from_user.username or "",
                "callback_data": callback.data,
                "callback_id": callback.id,
            }
            try:
                await worker.send(data)
            except ConnectionError:
                pass
            if callback.id:
                await callback.answer()

        # Drop pending updates to claim exclusive polling
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logger.warning("Failed to reset webhook: %s", e)

        for attempt in range(5):
            logger.info("Telegram polling started (attempt %d)", attempt + 1)
            try:
                await dp.start_polling(bot)
                break
            except Exception as e:
                if "Conflict" in str(e) and attempt < 4:
                    logger.warning("Polling conflict, retrying in %ds: %s", 2 * (attempt + 1), e)
                    await asyncio.sleep(2 * (attempt + 1))
                else:
                    logger.error("Telegram polling error: %s", e)
                    break

    async def _send_telegram(self, chat_id: str, text: str, parse_mode: str | None = None, reply_markup: dict | None = None) -> None:
        if not self._bot or not text:
            return
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = None
            if reply_markup and reply_markup.get("inline_keyboard"):
                rows = []
                for row in reply_markup["inline_keyboard"]:
                    rows.append([InlineKeyboardButton(text=btn["text"], callback_data=btn.get("callback_data", "")) for btn in row])
                kb = InlineKeyboardMarkup(inline_keyboard=rows)
            await self._bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=kb)
        except Exception as e:
            logger.error("Failed to send message: %s", e)

    async def _send_photo(self, chat_id: str, photo: str, caption: str = "") -> None:
        if not self._bot:
            return
        try:
            import base64
            from aiogram.types import BufferedInputFile
            photo_bytes = base64.b64decode(photo)
            await self._bot.send_photo(chat_id, BufferedInputFile(photo_bytes, "photo.jpg"), caption=caption)
        except Exception as e:
            logger.error("Failed to send photo: %s", e)


if __name__ == "__main__":
    TelegramWorker().run()
