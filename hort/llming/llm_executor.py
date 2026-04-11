"""LlmExecutor — base class for all LLM execution llmings.

Every LLM backend (Claude Code, Codex, llming-models, etc.) extends
this class. Chat operations are standard Powers, callable by connectors,
other llmings, or the chat backend router.

Session lifecycle: create → send → end.

    executor.execute_power("create_session", {"session_key": "alice", "model": "opus"})
    executor.execute_power("send_message", {"session_key": "alice", "text": "Hello"})
    executor.execute_power("end_session", {"session_key": "alice"})

To create a new LLM executor:

    class CodexExecutor(LlmExecutor):
        provider_name = "codex"
        async def _send(self, session_key, text, system_prompt):
            return SendResult(text="...", cost=0.01)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hort.llming.base import Llming
from hort.llming.powers import Power, PowerType


@dataclass
class SessionConfig:
    """Configuration for a new session."""

    model: str = ""  # Empty = use executor default
    system_prompt: str = ""
    budget_usd: float | None = None
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionInfo:
    """Tracks per-session state in the executor."""

    session_key: str
    config: SessionConfig = field(default_factory=SessionConfig)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turn_count: int = 0
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    provider_session_id: str = ""

    @property
    def budget_usd(self) -> float | None:
        return self.config.budget_usd

    @property
    def model(self) -> str:
        return self.config.model

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
            "system_prompt": bool(self.config.system_prompt),
            "allowed_tools": self.config.allowed_tools,
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

    Session lifecycle: create → send → end. No implicit creation.
    Subclass this and implement ``_send()`` at minimum.
    """

    provider_name: str = ""

    _sessions: dict[str, SessionInfo]

    def __init__(self) -> None:
        self._sessions = {}

    # ── Powers ──

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="create_session",
                type=PowerType.MCP,
                description="Create a new chat session with configuration",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string", "description": "Unique session identifier"},
                        "model": {"type": "string", "description": "Model override (empty = executor default)", "default": ""},
                        "system_prompt": {"type": "string", "description": "System prompt for this session", "default": ""},
                        "budget_usd": {"type": "number", "description": "Max spend in USD (null = unlimited)"},
                        "allowed_tools": {"type": "array", "items": {"type": "string"}, "description": "Tool allowlist (empty = all)", "default": []},
                    },
                    "required": ["session_key"],
                },
            ),
            Power(
                name="send_message",
                type=PowerType.MCP,
                description="Send a message to an existing session",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string", "description": "Target session"},
                        "text": {"type": "string", "description": "Message to send"},
                    },
                    "required": ["session_key", "text"],
                },
            ),
            Power(
                name="end_session",
                type=PowerType.MCP,
                description="End a session and release its resources",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string"},
                    },
                    "required": ["session_key"],
                },
            ),
            Power(
                name="get_session_status",
                type=PowerType.MCP,
                description="Get session state (turns, cost, model, config)",
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
        if name == "create_session":
            return await self._handle_create_session(args)
        if name == "send_message":
            return await self._handle_send(args["session_key"], args["text"])
        if name == "end_session":
            return await self._handle_end_session(args["session_key"])
        if name == "get_session_status":
            return self._handle_get_status(args["session_key"])
        if name == "list_sessions":
            return self._handle_list_sessions()
        if name == "get_usage":
            return self._handle_get_usage()
        return {"error": f"Unknown power: {name}"}

    # ── Power handlers ──

    async def _handle_create_session(self, args: dict[str, Any]) -> dict[str, Any]:
        session_key = args["session_key"]
        if session_key in self._sessions:
            return {"error": f"Session '{session_key}' already exists"}

        cfg = SessionConfig(
            model=args.get("model", ""),
            system_prompt=args.get("system_prompt", ""),
            budget_usd=args.get("budget_usd"),
            allowed_tools=args.get("allowed_tools", []),
            metadata=args.get("metadata", {}),
        )
        info = SessionInfo(session_key=session_key, config=cfg)
        self._sessions[session_key] = info
        await self._on_create_session(session_key, cfg)
        return {"ok": True, **info.to_dict()}

    async def _handle_send(self, session_key: str, text: str) -> dict[str, Any]:
        info = self._sessions.get(session_key)
        if info is None:
            return {"error": f"Session '{session_key}' does not exist. Call create_session first."}

        if info.budget_usd is not None and info.total_cost >= info.budget_usd:
            return {"error": f"Budget exceeded (${info.total_cost:.2f} / ${info.budget_usd:.2f})"}

        result = await self._send(session_key, text, info.config.system_prompt)
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

    async def _handle_end_session(self, session_key: str) -> dict[str, Any]:
        info = self._sessions.pop(session_key, None)
        if info is None:
            return {"error": f"Session '{session_key}' not found"}
        await self._on_end_session(session_key)
        return {"ok": True, "session_key": session_key, "turns": info.turn_count, "cost": round(info.total_cost, 4)}

    def _handle_get_status(self, session_key: str) -> dict[str, Any]:
        info = self._sessions.get(session_key)
        if info is None:
            return {"active": False, "session_key": session_key}
        return info.to_dict()

    def _handle_list_sessions(self) -> dict[str, Any]:
        return {
            "sessions": [info.to_dict() for info in self._sessions.values()],
            "count": len(self._sessions),
        }

    def _handle_get_usage(self) -> dict[str, Any]:
        return {
            "total_cost": round(sum(s.total_cost for s in self._sessions.values()), 4),
            "total_turns": sum(s.turn_count for s in self._sessions.values()),
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

        The ONE method every subclass MUST implement.
        """
        raise NotImplementedError

    async def _on_create_session(self, session_key: str, config: SessionConfig) -> None:
        """Called after a session is created. Override for provider-specific setup."""

    async def _on_end_session(self, session_key: str) -> None:
        """Called when a session ends. Override for provider-specific cleanup."""

    # ── Lifecycle ──

    def deactivate(self) -> None:
        """Clean up all sessions on shutdown."""
        self._sessions.clear()
