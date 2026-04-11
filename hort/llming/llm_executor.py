"""LlmExecutor — base class for all LLM execution llmings.

Every LLM backend (Claude Code, Codex, llming-models, etc.) extends
this class. Chat operations are standard Powers, callable by connectors,
other llmings, or the chat backend router.

To create a new LLM executor:

    class CodexExecutor(LlmExecutor):
        async def _send(self, session_key, text, system_prompt):
            # Call Codex API, return response
            ...

The base class provides:
- Standard Powers (send_message, reset_session, get_session_status, etc.)
- Session tracking and usage accounting
- Pulse with active session count and provider status
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hort.llming.base import Llming
from hort.llming.powers import Power, PowerType


@dataclass
class SessionInfo:
    """Tracks per-session state in the executor."""

    session_key: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turn_count: int = 0
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    budget_usd: float | None = None
    model: str = ""
    provider_session_id: str = ""  # Provider-specific ID (e.g. Claude session ID)

    def record_turn(self, cost: float = 0, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.turn_count += 1
        self.total_cost += cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.last_active = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_key": self.session_key,
            "active": True,
            "turn_count": self.turn_count,
            "total_cost": round(self.total_cost, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "budget_usd": self.budget_usd,
            "model": self.model,
            "provider_session_id": self.provider_session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
        }


@dataclass
class SendResult:
    """Result from _send(). Subclasses return this."""

    text: str
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    provider_session_id: str = ""
    tools_used: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class LlmExecutor(Llming):
    """Base class for LLM execution llmings.

    Subclass this and implement ``_send()`` at minimum. Override
    ``_create_session()``, ``_reset_session()``, ``_destroy_session()``
    for lifecycle control.

    All chat operations are exposed as Powers — callable by connectors,
    other llmings, or the chat backend.
    """

    # ── Subclass must set these ──

    provider_name: str = ""  # e.g. "claude-code", "codex", "llming-models"

    # ── Internal state ──

    _sessions: dict[str, SessionInfo]

    def __init__(self) -> None:
        self._sessions = {}

    # ── Powers ──

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="send_message",
                type=PowerType.MCP,
                description="Send a message and get a response",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string", "description": "User/conversation identifier"},
                        "text": {"type": "string", "description": "Message to send"},
                        "system_prompt": {"type": "string", "description": "Optional system prompt override", "default": ""},
                    },
                    "required": ["session_key", "text"],
                },
            ),
            Power(
                name="get_session_status",
                type=PowerType.MCP,
                description="Get session state (turns, cost, model)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string"},
                    },
                    "required": ["session_key"],
                },
            ),
            Power(
                name="reset_session",
                type=PowerType.MCP,
                description="Clear session history and start fresh",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string"},
                    },
                    "required": ["session_key"],
                },
            ),
            Power(
                name="list_sessions",
                type=PowerType.MCP,
                description="List all active sessions",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="get_usage",
                type=PowerType.MCP,
                description="Get total usage across all sessions",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        if name == "send_message":
            return await self._handle_send(
                args["session_key"], args["text"], args.get("system_prompt", ""),
            )
        if name == "get_session_status":
            return self._handle_get_status(args["session_key"])
        if name == "reset_session":
            return await self._handle_reset(args["session_key"])
        if name == "list_sessions":
            return self._handle_list_sessions()
        if name == "get_usage":
            return self._handle_get_usage()
        return {"error": f"Unknown power: {name}"}

    # ── Power handlers ──

    async def _handle_send(self, session_key: str, text: str, system_prompt: str) -> dict[str, Any]:
        info = self._sessions.get(session_key)
        if info is None:
            info = SessionInfo(session_key=session_key)
            self._sessions[session_key] = info
            await self._create_session(session_key)

        # Budget check
        if info.budget_usd is not None and info.total_cost >= info.budget_usd:
            return {"error": f"Budget exceeded (${info.total_cost:.2f} / ${info.budget_usd:.2f})"}

        result = await self._send(session_key, text, system_prompt)
        info.record_turn(result.cost, result.input_tokens, result.output_tokens)
        if result.provider_session_id:
            info.provider_session_id = result.provider_session_id

        return {
            "text": result.text,
            "cost": round(result.cost, 4),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "tools_used": result.tools_used,
            "turn_count": info.turn_count,
        }

    def _handle_get_status(self, session_key: str) -> dict[str, Any]:
        info = self._sessions.get(session_key)
        if info is None:
            return {"active": False, "session_key": session_key}
        return info.to_dict()

    async def _handle_reset(self, session_key: str) -> dict[str, Any]:
        if session_key in self._sessions:
            await self._reset_session(session_key)
            del self._sessions[session_key]
        return {"ok": True, "session_key": session_key}

    def _handle_list_sessions(self) -> dict[str, Any]:
        return {
            "sessions": [info.to_dict() for info in self._sessions.values()],
            "count": len(self._sessions),
        }

    def _handle_get_usage(self) -> dict[str, Any]:
        total_cost = sum(s.total_cost for s in self._sessions.values())
        total_turns = sum(s.turn_count for s in self._sessions.values())
        return {
            "total_cost": round(total_cost, 4),
            "total_turns": total_turns,
            "active_sessions": len(self._sessions),
            "provider": self.provider_name,
        }

    # ── Pulse ──

    def get_pulse(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "active_sessions": len(self._sessions),
            "total_turns": sum(s.turn_count for s in self._sessions.values()),
            "total_cost": round(sum(s.total_cost for s in self._sessions.values()), 4),
        }

    # ── Subclass interface ──

    async def _send(self, session_key: str, text: str, system_prompt: str) -> SendResult:
        """Send a message and return the response.

        This is the ONE method every subclass MUST implement.
        Called with the session_key (for multi-user support),
        the user's text, and an optional system prompt override.
        """
        raise NotImplementedError

    async def _create_session(self, session_key: str) -> None:
        """Called when a new session is created. Override for setup."""

    async def _reset_session(self, session_key: str) -> None:
        """Called when a session is reset. Override for cleanup."""

    async def _destroy_session(self, session_key: str) -> None:
        """Called when a session is permanently deleted. Override for cleanup."""

    # ── Lifecycle ──

    def deactivate(self) -> None:
        """Clean up all sessions on shutdown."""
        self._sessions.clear()
