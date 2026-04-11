"""Tests for LlmExecutor base class and the executor ecosystem."""

from __future__ import annotations

from typing import Any

import pytest

from hort.llming import LlmExecutor, SendResult, Power


class EchoExecutor(LlmExecutor):
    """Minimal executor that echoes back messages. For testing."""

    provider_name = "echo"

    async def _send(self, session_key: str, text: str, system_prompt: str) -> SendResult:
        return SendResult(
            text=f"echo: {text}",
            cost=0.001,
            input_tokens=len(text),
            output_tokens=len(text) + 6,
            provider_session_id=f"echo-{session_key}",
        )


class FailingExecutor(LlmExecutor):
    """Executor that always raises. For error handling tests."""

    provider_name = "failing"

    async def _send(self, session_key: str, text: str, system_prompt: str) -> SendResult:
        raise RuntimeError("LLM unavailable")


class TestLlmExecutorPowers:
    """Test that LlmExecutor provides the standard Powers interface."""

    def test_has_standard_powers(self) -> None:
        e = EchoExecutor()
        powers = e.get_powers()
        names = {p.name for p in powers}
        assert "send_message" in names
        assert "get_session_status" in names
        assert "reset_session" in names
        assert "list_sessions" in names
        assert "get_usage" in names

    def test_is_llming(self) -> None:
        from hort.llming.base import Llming
        e = EchoExecutor()
        assert isinstance(e, Llming)

    def test_provider_name(self) -> None:
        assert EchoExecutor().provider_name == "echo"


class TestLlmExecutorSendMessage:
    """Test the send_message power."""

    async def test_send_message(self) -> None:
        e = EchoExecutor()
        result = await e.execute_power("send_message", {
            "session_key": "user1",
            "text": "hello",
        })
        assert result["text"] == "echo: hello"
        assert result["cost"] == 0.001
        assert result["turn_count"] == 1

    async def test_send_tracks_session(self) -> None:
        e = EchoExecutor()
        await e.execute_power("send_message", {"session_key": "u1", "text": "a"})
        await e.execute_power("send_message", {"session_key": "u1", "text": "b"})

        status = await e.execute_power("get_session_status", {"session_key": "u1"})
        assert status["active"] is True
        assert status["turn_count"] == 2
        assert status["total_cost"] == pytest.approx(0.002)

    async def test_send_multiple_users(self) -> None:
        e = EchoExecutor()
        await e.execute_power("send_message", {"session_key": "alice", "text": "hi"})
        await e.execute_power("send_message", {"session_key": "bob", "text": "hey"})

        sessions = await e.execute_power("list_sessions", {})
        assert sessions["count"] == 2

    async def test_send_with_system_prompt(self) -> None:
        e = EchoExecutor()
        result = await e.execute_power("send_message", {
            "session_key": "u1",
            "text": "test",
            "system_prompt": "Be concise.",
        })
        assert result["text"] == "echo: test"


class TestLlmExecutorSessionManagement:
    """Test session lifecycle operations."""

    async def test_get_status_nonexistent(self) -> None:
        e = EchoExecutor()
        status = await e.execute_power("get_session_status", {"session_key": "nobody"})
        assert status["active"] is False

    async def test_reset_session(self) -> None:
        e = EchoExecutor()
        await e.execute_power("send_message", {"session_key": "u1", "text": "a"})
        await e.execute_power("reset_session", {"session_key": "u1"})

        status = await e.execute_power("get_session_status", {"session_key": "u1"})
        assert status["active"] is False

    async def test_reset_nonexistent_ok(self) -> None:
        e = EchoExecutor()
        result = await e.execute_power("reset_session", {"session_key": "ghost"})
        assert result["ok"] is True

    async def test_list_sessions_empty(self) -> None:
        e = EchoExecutor()
        sessions = await e.execute_power("list_sessions", {})
        assert sessions["count"] == 0

    async def test_get_usage(self) -> None:
        e = EchoExecutor()
        await e.execute_power("send_message", {"session_key": "u1", "text": "hi"})
        usage = await e.execute_power("get_usage", {})
        assert usage["total_turns"] == 1
        assert usage["total_cost"] > 0
        assert usage["provider"] == "echo"


class TestLlmExecutorBudget:
    """Test budget enforcement."""

    async def test_budget_exceeded(self) -> None:
        e = EchoExecutor()
        # Send a message to create the session
        await e.execute_power("send_message", {"session_key": "u1", "text": "a"})
        # Set a tiny budget
        e._sessions["u1"].budget_usd = 0.0001

        result = await e.execute_power("send_message", {"session_key": "u1", "text": "b"})
        assert "error" in result
        assert "Budget exceeded" in result["error"]


class TestLlmExecutorPulse:
    """Test pulse reporting."""

    def test_pulse_empty(self) -> None:
        e = EchoExecutor()
        pulse = e.get_pulse()
        assert pulse["provider"] == "echo"
        assert pulse["active_sessions"] == 0

    async def test_pulse_after_messages(self) -> None:
        e = EchoExecutor()
        await e.execute_power("send_message", {"session_key": "u1", "text": "hi"})
        pulse = e.get_pulse()
        assert pulse["active_sessions"] == 1
        assert pulse["total_turns"] == 1


class TestLlmExecutorErrorHandling:
    """Test that errors are handled gracefully."""

    async def test_unknown_power(self) -> None:
        e = EchoExecutor()
        result = await e.execute_power("nonexistent", {})
        assert "error" in result


class TestClaudeCodeExecutor:
    """Test the Claude Code executor imports and has correct interface."""

    def test_import(self) -> None:
        from llmings.core.claude_code.provider import ClaudeCodeExecutor
        e = ClaudeCodeExecutor()
        assert e.provider_name == "claude-code"
        assert isinstance(e, LlmExecutor)

    def test_has_standard_powers(self) -> None:
        from llmings.core.claude_code.provider import ClaudeCodeExecutor
        e = ClaudeCodeExecutor()
        names = {p.name for p in e.get_powers()}
        assert "send_message" in names
        assert "reset_session" in names


class TestLlmingModelsExecutor:
    """Test the llming-models executor imports and has correct interface."""

    def test_import(self) -> None:
        from llmings.llms.llming_models_ext.provider import LlmingModelsExecutor
        e = LlmingModelsExecutor()
        assert e.provider_name == "llming-models"
        assert isinstance(e, LlmExecutor)

    def test_has_standard_powers(self) -> None:
        from llmings.llms.llming_models_ext.provider import LlmingModelsExecutor
        e = LlmingModelsExecutor()
        names = {p.name for p in e.get_powers()}
        assert "send_message" in names
        assert "reset_session" in names
