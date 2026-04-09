"""Telegram Connector — Telegram bot that routes commands to openhort plugins.

Integrates with the connector framework:
- Registers system commands (help, link, status, targets)
- Discovers plugin commands via LlmingBase powers (windows, screenshot, etc.)
- Routes incoming messages through CommandRegistry
- Non-command messages route to Claude Code AI chat (if enabled)
- Sends responses adapted to Telegram capabilities

Requires: TELEGRAM_BOT_TOKEN env var, allowed_users in config.
AI chat requires: claude CLI installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from hort.ext.connectors import (
    CommandRegistry,
    ConnectorBase,
    ConnectorCapabilities,
    ConnectorCommand,
    ConnectorResponse,
    IncomingMessage,
)
from hort.llming import LlmingBase

logger = logging.getLogger("hort.connector.telegram")

# System commands that plugins cannot override
SYSTEM_COMMANDS = [
    ConnectorCommand(name="start", description="Welcome message", system=True),
    ConnectorCommand(name="help", description="List all commands", system=True),
    ConnectorCommand(name="link", description="Get a temporary access link", system=True),
    ConnectorCommand(name="status", description="Server status", system=True),
    ConnectorCommand(name="targets", description="List connected machines", system=True),
    ConnectorCommand(name="spaces", description="List/switch virtual desktops", system=True),
    ConnectorCommand(name="new", description="Start a new AI chat session", system=True),
]


class TelegramConnector(LlmingBase, ConnectorBase):
    """Telegram bot connector for openhort."""

    _bot: Any = None
    _task: Any = None
    _registry: CommandRegistry | None = None
    _allowed_users: list[str] = []
    _ai_chat: Any = None  # ChatBackendManager, created if chat config present

    @property
    def connector_id(self) -> str:
        return "telegram"


    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True, markdown=True, html=True,
            images=True, files=True,
            inline_buttons=True, commands=True,
            max_text_length=4096,
        )

    def activate(self, config: dict[str, Any]) -> None:
        self._allowed_users = config.get("allowed_users", [])
        # Safety: never allow connector without allowed_users
        if not self._allowed_users:
            self.log.warning("No allowed_users configured — Telegram connector will reject all messages")

        # Chat backend reads the shared agent config from hort-config.yaml.
        # Connector-level overrides (system_prompt) can be passed in chat.
        chat_config = config.get("chat", {})
        if chat_config.get("enabled", False):
            if not self._allowed_users:
                self.log.error("Chat backend DISABLED: allowed_users must be set for security")
            else:
                from hort.agent import get_agent_config
                from hort.ext.chat_backend import ChatBackendManager

                agent_cfg = get_agent_config()
                # Allow connector-level overrides for model and system_prompt
                if chat_config.get("model"):
                    agent_cfg = agent_cfg.model_copy(update={"model": chat_config["model"]})
                self._ai_chat = ChatBackendManager(
                    agent_cfg=agent_cfg,
                    system_prompt=chat_config.get("system_prompt", ""),
                )
                self.log.info(
                    "Chat backend enabled (model=%s, container=%s, dangerous=%s)",
                    agent_cfg.model or "default",
                    agent_cfg.container,
                    agent_cfg.dangerous_mode,
                )
        self.log.info("Telegram connector activated (allowed: %s)", self._allowed_users)

    def get_pulse(self) -> dict[str, Any]:
        """Status for connectors.list and llmings.pulse WS commands."""
        token_set = bool(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        task_error = ""
        if self._task and self._task.done():
            try:
                exc = self._task.exception()
                task_error = str(exc) if exc else ""
            except Exception:
                pass
        return {
            "active": self._bot is not None,
            "token_set": token_set,
            "allowed_users": self._allowed_users,
            "polling": self._task is not None and not self._task.done(),
            "error": task_error,
        }

    async def start(self) -> None:
        """Start the Telegram bot polling and MCP bridge (if AI chat enabled)."""
        # Start MCP bridge for AI chat
        if self._ai_chat:
            try:
                self._ai_chat.start()
            except Exception as exc:
                self.log.error("Failed to start MCP bridge: %s", exc)

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            self.log.warning("TELEGRAM_BOT_TOKEN not set — Telegram connector disabled")
            return

        try:
            from aiogram import Bot, Dispatcher
            from aiogram.types import Message, CallbackQuery
        except ImportError:
            self.log.warning("aiogram not installed — Telegram connector disabled")
            return

        bot = Bot(token=token)
        dp = Dispatcher()
        self._bot = bot

        connector = self

        @dp.message()
        async def handle_message(message: Message) -> None:
            if not message.from_user:
                return
            username = message.from_user.username or ""
            self.log.info("Incoming message from @%s: %s", username, (message.text or "")[:80])
            if connector._allowed_users and username not in connector._allowed_users:
                self.log.info("ACL rejected user @%s (allowed: %s)", username, connector._allowed_users)
                return

            msg = IncomingMessage(
                connector_id="telegram",
                chat_id=str(message.chat.id),
                user_id=str(message.from_user.id),
                username=username,
                text=message.text or "",
            )
            try:
                response = await connector._handle(msg)
                if response:
                    self.log.info("Sending response: text=%d chars", len(response.text or ""))
                    await connector.send_response(str(message.chat.id), response)
                else:
                    self.log.info("No response for message")
            except Exception:
                self.log.exception("Error handling message")
                try:
                    await bot.send_message(str(message.chat.id), "Something went wrong. Try again.")
                except Exception:
                    pass

        @dp.callback_query()
        async def handle_callback(callback: CallbackQuery) -> None:
            if not callback.from_user or not callback.data:
                return
            username = callback.from_user.username or ""
            if connector._allowed_users and username not in connector._allowed_users:
                return

            msg = IncomingMessage(
                connector_id="telegram",
                chat_id=str(callback.message.chat.id) if callback.message else "",
                user_id=str(callback.from_user.id),
                username=username,
                callback_data=callback.data,
            )
            try:
                response = await connector._handle(msg)
                if response and callback.message:
                    await connector.send_response(str(callback.message.chat.id), response)
            except Exception as e:
                self.log.error("Error handling callback: %s", e, exc_info=True)
            if callback.id:
                await callback.answer()

        async def polling() -> None:
            # Drop pending updates to claim exclusive polling (kills old instances)
            try:
                await bot.delete_webhook(drop_pending_updates=True)
            except Exception as e:
                self.log.warning("Failed to reset webhook: %s", e)

            for attempt in range(5):
                self.log.info("Telegram bot polling started (attempt %d)", attempt + 1)
                try:
                    await dp.start_polling(bot)
                    break
                except Exception as e:
                    if "Conflict" in str(e) and attempt < 4:
                        self.log.warning("Polling conflict, retrying in %ds: %s", 2 * (attempt + 1), e)
                        await asyncio.sleep(2 * (attempt + 1))
                    else:
                        self.log.error("Telegram polling error: %s", e)
                        break

        self._task = asyncio.create_task(polling())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._bot:
            await self._bot.session.close()
        if self._ai_chat:
            self._ai_chat.stop()

    async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
        """Send response to Telegram chat."""
        if not self._bot:
            return

        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

        # Build keyboard if buttons provided
        keyboard = None
        if response.buttons:
            rows = []
            for row in response.buttons:
                btns = []
                for btn in row:
                    if btn.callback_data.startswith("p2p_webapp:"):
                        # Web App button — opens URL in Telegram WebView
                        url = btn.callback_data[len("p2p_webapp:"):]
                        btns.append(InlineKeyboardButton(
                            text=btn.label,
                            web_app=WebAppInfo(url=url),
                        ))
                    else:
                        btns.append(InlineKeyboardButton(text=btn.label, callback_data=btn.callback_data))
                rows.append(btns)
            keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

        # Send image if provided
        if response.image:
            from aiogram.types import BufferedInputFile
            photo = BufferedInputFile(response.image, filename="screenshot.jpg")
            await self._bot.send_photo(
                chat_id, photo,
                caption=response.image_caption or response.text or "",
                reply_markup=keyboard,
            )
            return

        # Send text
        text = self.render_text(response)
        if not text:
            return

        # Split long messages
        parse_mode = "HTML" if response.html else ("Markdown" if response.markdown else None)
        for i in range(0, len(text), 4096):
            chunk = text[i:i + 4096]
            try:
                await self._bot.send_message(
                    chat_id, chunk,
                    parse_mode=parse_mode,
                    reply_markup=keyboard if i == 0 else None,
                )
            except Exception as e:
                self.log.warning("Failed to send with parse_mode=%s: %s — falling back to plain text", parse_mode, e)
                # Retry without parse_mode
                plain = response.text or text
                for j in range(0, len(plain), 4096):
                    await self._bot.send_message(
                        chat_id, plain[j:j + 4096],
                        reply_markup=keyboard if j == 0 else None,
                    )
                break

    def set_command_registry(self, registry: CommandRegistry) -> None:
        self._registry = registry

    async def _handle(self, message: IncomingMessage) -> ConnectorResponse | None:
        """Handle incoming message — system commands, plugins, or AI chat."""
        if message.callback_data:
            return await self._handle_callback(message)

        if not message.is_command:
            # Route non-command messages to chat backend (if configured)
            if self._ai_chat and message.text:
                return await self._handle_chat(message)
            return ConnectorResponse.simple("Send /help for available commands.")

        cmd = message.command

        # System commands
        if cmd == "start":
            return self._cmd_start()
        if cmd == "help":
            return self._cmd_help()
        if cmd == "link":
            return await self._cmd_link()
        if cmd == "status":
            return await self._cmd_status()
        if cmd == "targets":
            return await self._cmd_targets()
        if cmd == "spaces":
            return await self._cmd_spaces()
        if cmd == "new":
            return self._cmd_new(message)
        # Plugin commands via registry
        if self._registry:
            result = await self._registry.dispatch(message, self.capabilities)
            if result:
                return result

        return ConnectorResponse.simple(f"Unknown command: /{cmd}\nSend /help for available commands.")

    async def _handle_callback(self, message: IncomingMessage) -> ConnectorResponse | None:
        """Handle inline button callbacks."""
        data = message.callback_data or ""
        if data.startswith("space:"):
            idx = int(data.split(":")[1])
            return ConnectorResponse.simple(f"Switched to Space {idx}")
        # Route plugin callbacks: "plugin_id:callback_payload"
        if self._registry and ":" in data:
            prefix = data.split(":", 1)[0]
            plugin = self._registry.get_plugin(prefix)
            if plugin:
                return await plugin.handle_connector_command(
                    "_callback", message, self.capabilities
                )
        return None

    # ===== System Commands =====

    def _cmd_start(self) -> ConnectorResponse:
        return ConnectorResponse(
            text="Welcome to OpenHORT!\n\nControl your machine remotely.\nSend /help for available commands.",
            html="<b>Welcome to OpenHORT!</b> 🏠\n\nControl your machine remotely.\nSend /help for available commands.",
        )

    def _cmd_help(self) -> ConnectorResponse:
        text_lines = ["Available Commands\n", "System:"]
        html_lines = ["<b>Available Commands</b>\n", "<b>System:</b>"]
        for cmd in SYSTEM_COMMANDS:
            if not cmd.hidden:
                text_lines.append(f"  /{cmd.name} — {cmd.description}")
                html_lines.append(f"  /{cmd.name} — {cmd.description}")

        if self._registry:
            plugin_cmds = [c for c in self._registry.get_all_commands() if c.plugin_id and not c.system]
            if plugin_cmds:
                text_lines.append("\nPlugins:")
                html_lines.append("\n<b>Plugins:</b>")
                for cmd in plugin_cmds:
                    text_lines.append(f"  /{cmd.name} — {cmd.description}")
                    html_lines.append(f"  /{cmd.name} — {cmd.description}")

        return ConnectorResponse(text="\n".join(text_lines), html="\n".join(html_lines))

    async def _cmd_link(self) -> ConnectorResponse:
        """Generate a fresh temporary access link (24h). Multiple links can coexist."""
        from hort.config import get_store
        cloud = get_store().get("connector.cloud")
        server = cloud.get("server", "")
        host_id = cloud.get("host_id", "")

        if not server or not host_id:
            return ConnectorResponse.simple("Cloud connector not configured. Access locally.")

        # Create a fresh token every time (old ones stay valid until they expire)
        from hort.access.tokens import TokenStore
        store = TokenStore()
        token = store.create_temporary("Telegram /link", duration_seconds=86400)

        url = f"{server}/t/{host_id}/{token}"
        return ConnectorResponse(
            text=f"Temporary access link (24h):\n{url}",
            html=f"🔗 <b>Temporary access link</b> (24h):\n{url}",
        )

    async def _cmd_status(self) -> ConnectorResponse:
        """Server status summary."""
        import platform
        import psutil

        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        uptime = time.time() - psutil.boot_time()
        hours = int(uptime // 3600)

        text = (
            f"🖥 {platform.node()}\n"
            f"CPU: {cpu}% ({psutil.cpu_count()} cores)\n"
            f"Memory: {mem.percent}% ({round(mem.used/1024**3,1)}/{round(mem.total/1024**3,1)} GB)\n"
            f"Uptime: {hours}h"
        )
        return ConnectorResponse.simple(text)

    async def _cmd_targets(self) -> ConnectorResponse:
        """List connected targets."""
        from hort.targets import TargetRegistry
        registry = TargetRegistry.get()
        targets = registry.list_targets()
        if not targets:
            return ConnectorResponse.simple("No targets connected.")
        text_lines = ["Connected Targets:"]
        html_lines = ["<b>Connected Targets:</b>"]
        for t in targets:
            text_lines.append(f"  • {t.name} ({t.provider_type})")
            html_lines.append(f"  • {t.name} ({t.provider_type})")
        return ConnectorResponse(text="\n".join(text_lines), html="\n".join(html_lines))

    async def _cmd_spaces(self) -> ConnectorResponse:
        """List virtual desktops."""
        return ConnectorResponse.simple("Spaces listing via Telegram — coming soon.")

    def _cmd_new(self, message: IncomingMessage) -> ConnectorResponse:
        """Reset chat session for this user."""
        if self._ai_chat:
            self._ai_chat.reset_session(message.user_id)
            return ConnectorResponse.simple("New chat session started.")
        return ConnectorResponse.simple("Chat backend not enabled.")

    async def _handle_chat(self, message: IncomingMessage) -> ConnectorResponse:
        """Route a non-command message to the chat backend."""
        assert self._ai_chat is not None
        if not self._ai_chat.alive:
            return ConnectorResponse.simple("Chat backend not running.")

        # Resolve user from hort-config.yaml for group-based session management
        from hort.hort_config import get_hort_config
        hort_cfg = get_hort_config()
        user_cfg = hort_cfg.get_user_by_match("telegram", message.username or "")
        if user_cfg:
            # Use group session policy: "shared" = same session across connectors
            groups = hort_cfg.get_user_groups(user_cfg)
            session_key = user_cfg.name  # default: user name as session key
            for g in groups:
                if g.session == "shared":
                    session_key = f"shared:{user_cfg.name}"
                    break
                elif g.session == "isolated":
                    session_key = f"telegram:{message.user_id}"
                    break
            session = self._ai_chat.get_session(session_key)
        else:
            session = self._ai_chat.get_session(message.user_id)

        # Progress callback: Telegram only shows periodic "thinking" updates,
        # NOT individual tool events (those are for richer UIs like web chat)
        from hort.ext.chat_backend import ChatProgressEvent

        async def on_progress(event: ChatProgressEvent) -> None:
            if event.kind != "thinking":
                return  # Skip tool_start etc. — too noisy for Telegram
            try:
                status = "Thinking..."
                if event.tools_used:
                    status = f"Working... (used {len(event.tools_used)} tools)"
                await self.send_response(message.chat_id, ConnectorResponse.simple(status))
            except Exception:
                pass

        try:
            response_text = await session.send(message.text or "", on_progress=on_progress)
            # Truncate very long responses (e.g. if Claude includes base64 data)
            if len(response_text) > 8000:
                response_text = response_text[:8000] + "\n... (truncated)"
            # Split into 4000-char chunks for Telegram
            chunks: list[str] = []
            while response_text:
                chunks.append(response_text[:4000])
                response_text = response_text[4000:]
            if not chunks:
                chunks = ["(no response)"]
            for chunk in chunks[:-1]:
                try:
                    await self.send_response(message.chat_id, ConnectorResponse.simple(chunk))
                except Exception:
                    pass  # Best effort for intermediate chunks
            return ConnectorResponse.simple(chunks[-1])
        except Exception:
            self.log.exception("Chat backend error")
            return ConnectorResponse.simple("Something went wrong. Try /new to reset.")
