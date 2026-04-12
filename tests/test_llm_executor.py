"""Tests for LlmExecutor base class and the executor ecosystem.

Session lifecycle: create → send → end. No auto-create, no reset.
"""

from __future__ import annotations

from typing import Any

import pytest

from hort.llming import LlmExecutor, SendResult, SessionConfig


class EchoExecutor(LlmExecutor):
    """Minimal executor that echoes back messages. For testing."""

    provider_name = "echo"
    _created: list[str]  # track create calls for testing

    def __init__(self) -> None:
        super().__init__()
        self._created = []

    async def _send(self, session_key: str, text: str, system_prompt: str) -> SendResult:
        return SendResult(
            text=f"echo: {text}",
            cost=0.001,
            input_tokens=len(text),
            output_tokens=len(text) + 6,
            provider_session_id=f"echo-{session_key}",
        )

    async def _on_create_session(self, session_key: str, config: SessionConfig) -> None:
        self._created.append(session_key)

    async def _on_end_session(self, session_key: str) -> None:
        pass


class TestLlmExecutorPowers:

    def test_has_standard_powers(self) -> None:
        e = EchoExecutor()
        names = {p.name for p in e.get_powers()}
        assert names == {"create_session", "send_message", "end_session", "get_session_status", "list_sessions", "get_usage"}

    def test_is_llming(self) -> None:
        from hort.llming.base import Llming
        assert isinstance(EchoExecutor(), Llming)

    def test_provider_name(self) -> None:
        assert EchoExecutor().provider_name == "echo"


class TestSessionLifecycle:
    """create → send → end"""

    async def test_create_then_send(self) -> None:
        e = EchoExecutor()
        create = await e.execute_power("create_session", {"session_key": "s1"})
        assert create["ok"] is True

        result = await e.execute_power("send_message", {"session_key": "s1", "text": "hello"})
        assert result["text"] == "echo: hello"
        assert result["turn_count"] == 1

    async def test_send_without_create_fails(self) -> None:
        e = EchoExecutor()
        result = await e.execute_power("send_message", {"session_key": "ghost", "text": "hi"})
        assert "error" in result
        assert "does not exist" in result["error"]

    async def test_create_duplicate_fails(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1"})
        result = await e.execute_power("create_session", {"session_key": "s1"})
        assert "error" in result
        assert "already exists" in result["error"]

    async def test_end_session(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1"})
        await e.execute_power("send_message", {"session_key": "s1", "text": "a"})

        end = await e.execute_power("end_session", {"session_key": "s1"})
        assert end["ok"] is True
        assert end["turns"] == 1

        # Session is gone
        status = await e.execute_power("get_session_status", {"session_key": "s1"})
        assert status["active"] is False

    async def test_end_nonexistent_fails(self) -> None:
        e = EchoExecutor()
        result = await e.execute_power("end_session", {"session_key": "ghost"})
        assert "error" in result

    async def test_send_after_end_fails(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1"})
        await e.execute_power("end_session", {"session_key": "s1"})

        result = await e.execute_power("send_message", {"session_key": "s1", "text": "hi"})
        assert "error" in result

    async def test_create_calls_hook(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1"})
        assert "s1" in e._created


class TestSessionConfig:
    """Session creation with specific configuration."""

    async def test_create_with_model(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1", "model": "opus"})
        status = await e.execute_power("get_session_status", {"session_key": "s1"})
        assert status["model"] == "opus"

    async def test_create_with_budget(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1", "budget_usd": 5.0})
        status = await e.execute_power("get_session_status", {"session_key": "s1"})
        assert status["budget_usd"] == 5.0

    async def test_create_with_system_prompt(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1", "system_prompt": "Be brief."})
        status = await e.execute_power("get_session_status", {"session_key": "s1"})
        assert status["system_prompt"] is True  # bool indicating it's set

    async def test_create_with_tools(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {
            "session_key": "s1",
            "allowed_tools": ["Read", "Write"],
        })
        status = await e.execute_power("get_session_status", {"session_key": "s1"})
        assert status["allowed_tools"] == ["Read", "Write"]


class TestMultipleSessions:

    async def test_multiple_sessions(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "alice"})
        await e.execute_power("create_session", {"session_key": "bob"})
        await e.execute_power("send_message", {"session_key": "alice", "text": "a"})
        await e.execute_power("send_message", {"session_key": "bob", "text": "b"})

        sessions = await e.execute_power("list_sessions", {})
        assert sessions["count"] == 2

    async def test_sessions_isolated(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "a"})
        await e.execute_power("create_session", {"session_key": "b"})
        await e.execute_power("send_message", {"session_key": "a", "text": "1"})
        await e.execute_power("send_message", {"session_key": "a", "text": "2"})
        await e.execute_power("send_message", {"session_key": "b", "text": "x"})

        sa = await e.execute_power("get_session_status", {"session_key": "a"})
        sb = await e.execute_power("get_session_status", {"session_key": "b"})
        assert sa["turn_count"] == 2
        assert sb["turn_count"] == 1

    async def test_new_session_after_end(self) -> None:
        """End a session and create a fresh one with same key."""
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1"})
        await e.execute_power("send_message", {"session_key": "s1", "text": "old"})
        await e.execute_power("end_session", {"session_key": "s1"})

        # Create new session with same key
        await e.execute_power("create_session", {"session_key": "s1", "model": "new-model"})
        status = await e.execute_power("get_session_status", {"session_key": "s1"})
        assert status["turn_count"] == 0  # fresh
        assert status["model"] == "new-model"


class TestBudget:

    async def test_budget_exceeded(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1", "budget_usd": 0.0005})
        await e.execute_power("send_message", {"session_key": "s1", "text": "a"})  # costs 0.001

        result = await e.execute_power("send_message", {"session_key": "s1", "text": "b"})
        assert "error" in result
        assert "Budget exceeded" in result["error"]


class TestUsageAndPulse:

    async def test_get_usage(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1"})
        await e.execute_power("send_message", {"session_key": "s1", "text": "hi"})
        usage = await e.execute_power("get_usage", {})
        assert usage["total_turns"] == 1
        assert usage["total_cost"] > 0
        assert usage["provider"] == "echo"

    def test_pulse_empty(self) -> None:
        e = EchoExecutor()
        pulse = e.get_pulse()
        assert pulse["provider"] == "echo"
        assert pulse["active_sessions"] == 0

    async def test_pulse_after_messages(self) -> None:
        e = EchoExecutor()
        await e.execute_power("create_session", {"session_key": "s1"})
        await e.execute_power("send_message", {"session_key": "s1", "text": "hi"})
        pulse = e.get_pulse()
        assert pulse["active_sessions"] == 1
        assert pulse["total_turns"] == 1


class TestClaudeCodeExecutor:

    def test_import_and_interface(self) -> None:
        from llmings.core.claude_code.claude_code import ClaudeCodeExecutor
        e = ClaudeCodeExecutor()
        assert e.provider_name == "claude-code"
        assert isinstance(e, LlmExecutor)
        names = {p.name for p in e.get_powers()}
        assert "create_session" in names
        assert "send_message" in names
        assert "end_session" in names


class TestLlmingModelsExecutor:

    def test_import_and_interface(self) -> None:
        from llmings.llms.llming_models_ext.llming_models_ext import LlmingModelsExecutor
        e = LlmingModelsExecutor()
        assert e.provider_name == "llming-models"
        assert isinstance(e, LlmExecutor)
        names = {p.name for p in e.get_powers()}
        assert "create_session" in names
        assert "send_message" in names
        assert "end_session" in names
