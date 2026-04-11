"""Telegram Connector — Telegram bot that routes commands to openhort plugins.

Integrates with the connector framework:
- Registers system commands (help, link, status, targets)
- Discovers plugin commands via Llming powers (windows, screenshot, etc.)
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
from hort.llming import Llming

logger = logging.getLogger("hort.connector.telegram")

# System commands that plugins cannot override
def _is_internal_error(text: str) -> bool:
    """Detect API errors and internal details that must not reach users."""
    markers = [
        "authentication_error", "Invalid API key", "invalid_api_key",
        "Invalid authentication credentials", "API Error:", "Failed to authenticate",
        "Traceback (most recent call last)", "request_id\":\"req_",
        "overloaded_error", "rate_limit_error",
    ]
    return any(m in text for m in markers)


SYSTEM_COMMANDS = [
    ConnectorCommand(name="start", description="Welcome message", system=True),
    ConnectorCommand(name="help", description="List all commands", system=True),
    ConnectorCommand(name="link", description="Get a temporary access link", system=True),
    ConnectorCommand(name="status", description="Server status", system=True),
    ConnectorCommand(name="targets", description="List connected machines", system=True),
    ConnectorCommand(name="spaces", description="List/switch virtual desktops", system=True),
    ConnectorCommand(name="new", description="Start a new AI chat session", system=True),
]


class TelegramConnector(Llming, ConnectorBase):
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
                from hort.ext.chat_backend import get_chat_manager
                self._ai_chat = get_chat_manager()
                self.log.info("Chat backend enabled (shared manager)")
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
        """Start the Telegram bot as a managed subprocess."""
        if self._ai_chat:
            try:
                self._ai_chat.start()
            except Exception as exc:
                self.log.error("Failed to start MCP bridge: %s", exc)

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            self.log.warning("TELEGRAM_BOT_TOKEN not set — Telegram connector disabled")
            return

        from hort.lifecycle import ManagedProcess
        import sys

        connector = self

        class _TelegramProcess(ManagedProcess):
            name = "telegram"
            protocol_version = 1

            def build_command(self) -> list[str]:
                return [sys.executable, "-m", "hort.extensions.core.telegram_connector.worker"]

            def get_env(self) -> dict[str, str]:
                return {"TELEGRAM_BOT_TOKEN": token}

            async def on_message(self, msg: dict) -> None:
                await connector._handle_worker_message(msg)

            async def on_connected(self) -> None:
                connector.log.info("Telegram worker connected")

        self._managed = _TelegramProcess()
        ok = await self._managed.start()
        if ok:
            self.log.info("Telegram bot polling started (managed subprocess)")
        else:
            self.log.error("Failed to start Telegram subprocess")

    async def stop(self) -> None:
        if hasattr(self, "_managed") and self._managed:
            await self._managed.stop()
        if self._ai_chat:
            self._ai_chat.stop()

    async def detach(self) -> None:
        """Hot-reload: keep subprocess alive, disconnect IPC."""
        if hasattr(self, "_managed") and self._managed:
            await self._managed.detach()

    async def _handle_worker_message(self, msg: dict) -> None:
        """Handle messages from the Telegram worker subprocess."""
        msg_type = msg.get("type", "")

        if msg_type == "telegram_message":
            username = msg.get("username", "")
            self.log.info("Incoming message from @%s: %s", username, msg.get("text", "")[:80])

            if self._allowed_users and username not in self._allowed_users:
                self.log.info("ACL rejected user @%s", username)
                return

            incoming = IncomingMessage(
                connector_id="telegram",
                chat_id=msg.get("chat_id", ""),
                user_id=msg.get("user_id", ""),
                username=username,
                text=msg.get("text", ""),
            )
            try:
                response = await self._handle(incoming)
                if response:
                    await self._send_via_worker(msg.get("chat_id", ""), response)
            except Exception:
                self.log.exception("Error handling message")
                await self._send_text_via_worker(msg.get("chat_id", ""), "Something went wrong. Try again.")

        elif msg_type == "telegram_callback":
            username = msg.get("username", "")
            if self._allowed_users and username not in self._allowed_users:
                return

            incoming = IncomingMessage(
                connector_id="telegram",
                chat_id=msg.get("chat_id", ""),
                user_id=msg.get("user_id", ""),
                username=username,
                callback_data=msg.get("callback_data", ""),
            )
            try:
                response = await self._handle(incoming)
                if response:
                    await self._send_via_worker(msg.get("chat_id", ""), response)
            except Exception:
                self.log.exception("Error handling callback")

    async def _send_via_worker(self, chat_id: str, response: ConnectorResponse) -> None:
        """Send a response through the worker subprocess."""
        if not hasattr(self, "_managed") or not self._managed or not self._managed.connected:
            return

        # Build reply_markup for inline buttons
        reply_markup = None
        if response.buttons:
            rows = []
            for row in response.buttons:
                rows.append([{"text": btn.label, "callback_data": btn.callback_data} for btn in row])
            reply_markup = {"inline_keyboard": rows}

        if response.image:
            import base64
            await self._managed.send({
                "type": "send_photo",
                "chat_id": chat_id,
                "photo": base64.b64encode(response.image).decode(),
                "caption": response.image_caption or response.text or "",
            })
            return

        text = self.render_text(response)
        if not text:
            return

        parse_mode = "HTML" if response.html else None
        await self._managed.send({
            "type": "send_message",
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })

    async def _send_text_via_worker(self, chat_id: str, text: str) -> None:
        if hasattr(self, "_managed") and self._managed and self._managed.connected:
            await self._managed.send({"type": "send_message", "chat_id": chat_id, "text": text})

    async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
        """Send response to Telegram via the worker subprocess."""
        await self._send_via_worker(chat_id, response)

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
            # Sanitize: never expose API errors or internal details to users
            if response_text and _is_internal_error(response_text):
                self.log.warning("Sanitized internal error from AI response")
                response_text = "Something went wrong. Try again in a moment."
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
