"""LlmingWire — built-in chat UI for openhort.

Provides a WhatsApp/Telegram-style chat interface in the browser.
Messages are sent to the chat backend (Claude Code) and responses
stream back as bubbles.

The UI is entirely in ``static/panel.js`` — this provider just
exposes the REST API endpoints for sending messages and polling
responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from hort.ext.plugin import PluginBase

logger = logging.getLogger("hort.plugin.llming-wire")

router = APIRouter()


class LlmingWire(PluginBase):
    """Chat UI llming — built-in messenger for your hort."""

    _conversations: dict[str, list[dict[str, Any]]] = {}
    _router: APIRouter | None = None

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("LlmingWire chat activated")

    def get_router(self) -> APIRouter:
        """Register REST endpoints for the chat UI."""
        if self._router:
            return self._router

        plugin = self

        r = APIRouter()

        @r.get("/conversations")
        async def list_conversations() -> JSONResponse:
            return JSONResponse([
                {"id": cid, "message_count": len(msgs), "last": msgs[-1] if msgs else None}
                for cid, msgs in plugin._conversations.items()
            ])

        @r.post("/conversations")
        async def create_conversation() -> JSONResponse:
            cid = uuid.uuid4().hex[:12]
            plugin._conversations[cid] = []
            return JSONResponse({"id": cid})

        @r.get("/conversations/{cid}/messages")
        async def get_messages(cid: str) -> JSONResponse:
            msgs = plugin._conversations.get(cid, [])
            return JSONResponse(msgs)

        @r.post("/conversations/{cid}/messages")
        async def send_message(cid: str, request: Request) -> JSONResponse:
            body = await request.json()
            text = body.get("text", "")
            if not text:
                return JSONResponse({"error": "empty message"}, status_code=400)

            if cid not in plugin._conversations:
                plugin._conversations[cid] = []

            # Handle slash commands (same as Telegram)
            if text.startswith("/"):
                cmd = text.strip().lstrip("/").split()[0].lower()
                result = await plugin._handle_command(cid, cmd)
                if result:
                    return JSONResponse(result)

            # Add user message
            user_msg = {
                "id": uuid.uuid4().hex[:8],
                "role": "user",
                "text": text,
                "ts": time.time(),
            }
            plugin._conversations[cid].append(user_msg)

            # Get AI response via chat backend
            client_session_id = body.get("session_id")
            try:
                response_text = await plugin._get_ai_response(cid, text, client_session_id)
            except Exception as exc:
                logger.error("Chat error: %s", exc)
                response_text = f"Error: {exc}"

            # Parse response for buttons (lines like "1. Option" become buttons)
            buttons = _extract_buttons(response_text)
            clean_text = response_text if not buttons else _strip_button_lines(response_text)

            # Get session_id from the chat session for --resume
            session = plugin._chat_mgr.get_session(f"llming-wire:{cid}") if hasattr(plugin, '_chat_mgr') and plugin._chat_mgr else None
            resume_id = session._session_id if session else None

            ai_msg = {
                "id": uuid.uuid4().hex[:8],
                "role": "assistant",
                "text": clean_text,
                "ts": time.time(),
                "buttons": buttons,
                "session_id": resume_id,
            }
            plugin._conversations[cid].append(ai_msg)

            return JSONResponse(ai_msg)

        self._router = r
        return r

    async def _handle_command(self, cid: str, cmd: str) -> dict[str, Any] | None:
        """Handle slash commands — uses the same CommandRegistry as Telegram."""
        def _reply(text: str, session_id: Any = ...) -> dict[str, Any]:
            r: dict[str, Any] = {
                "id": uuid.uuid4().hex[:8],
                "role": "assistant",
                "text": text,
                "ts": time.time(),
                "buttons": [],
            }
            if session_id is not ...:
                r["session_id"] = session_id
            return r

        # Built-in: /new resets the chat session
        if cmd == "new":
            if hasattr(self, "_chat_mgr") and self._chat_mgr:
                self._chat_mgr.reset_session(f"llming-wire:{cid}")
            return _reply("New chat session started.", session_id=None)

        # Built-in: /help lists all available commands
        if cmd == "help":
            lines = ["/new — start a fresh conversation"]
            try:
                from hort.plugins import get_command_registry
                registry = get_command_registry()
                if registry:
                    for c in registry.get_all_commands():
                        if not c.hidden:
                            lines.append(f"/{c.name} — {c.description}")
            except Exception:
                pass
            return _reply("\n".join(lines))

        # Try the shared command registry (same commands as Telegram)
        try:
            from hort.plugins import get_command_registry
            from hort.ext.connectors import IncomingMessage, ConnectorCapabilities

            registry = get_command_registry()
            if registry:
                msg = IncomingMessage(
                    connector_id="llming-wire",
                    chat_id=cid,
                    user_id="local",
                    username="local",
                    text=f"/{cmd}",
                )
                caps = ConnectorCapabilities(text=True)
                result = await registry.dispatch(msg, caps)
                if result:
                    text = result.text or result.html or result.markdown or ""
                    return _reply(text)
        except Exception as exc:
            logger.debug("Command dispatch failed: %s", exc)

        return None  # Unknown — pass to AI

    async def _get_ai_response(self, cid: str, text: str, client_session_id: str | None = None) -> str:
        """Route message to the chat backend and return the response."""
        try:
            from hort.ext.chat_backend import ChatBackendManager

            # Find or create a chat backend manager (host mode, no container)
            if not hasattr(self, "_chat_mgr") or self._chat_mgr is None:
                from hort.agent import AgentConfig
                cfg = AgentConfig(container=False)
                self._chat_mgr = ChatBackendManager(agent_cfg=cfg)
                self._chat_mgr.start()

            session = self._chat_mgr.get_session(f"llming-wire:{cid}")
            # Resume from client's session_id if server lost it (restart)
            if client_session_id and not session._session_id:
                session._session_id = client_session_id
            response = await session.send(text)
            return response
        except ImportError:
            return "Chat backend not available. Install claude CLI."
        except Exception as exc:
            return f"Error: {exc}"


def _extract_buttons(text: str) -> list[dict[str, str]]:
    """Extract numbered options from response text as buttons.

    Lines like "1. Fix the bug" become buttons the user can tap.
    """
    import re
    buttons = []
    for match in re.finditer(r"^\s*(\d+)\.\s+(.+)$", text, re.MULTILINE):
        num = match.group(1)
        label = match.group(2).strip()
        if len(label) < 100:  # reasonable button length
            buttons.append({"id": num, "label": f"{num}. {label}"})
    # Only return buttons if there are 2-10 options (likely a choice)
    if 2 <= len(buttons) <= 10:
        return buttons
    return []


def _strip_button_lines(text: str) -> str:
    """Remove numbered option lines from text (shown as buttons instead)."""
    import re
    return re.sub(r"^\s*\d+\.\s+.+$", "", text, flags=re.MULTILINE).strip()
