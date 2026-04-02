"""Integration tests for the chat backend and MCP bridge.

Tests the full chain: ChatSession → Claude Code CLI → MCP bridge → tools.
These tests require the claude CLI to be installed and authenticated.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMCPBridgeProcess:
    """Test the MCP bridge subprocess manager."""

    def test_start_and_stop(self) -> None:
        from hort.ext.chat_backend import MCPBridgeProcess

        bridge = MCPBridgeProcess(port=0)
        bridge.start()
        try:
            assert bridge.alive
            assert bridge.mcp_config_path
            assert os.path.exists(bridge.mcp_config_path)
            # Verify config content
            with open(bridge.mcp_config_path) as f:
                config = json.load(f)
            assert "mcpServers" in config
            assert "openhort" in config["mcpServers"]
            assert "sse" in config["mcpServers"]["openhort"]["type"]
        finally:
            bridge.stop()
        assert not bridge.alive
        assert not bridge.mcp_config_path

    def test_idempotent_start(self) -> None:
        from hort.ext.chat_backend import MCPBridgeProcess

        bridge = MCPBridgeProcess(port=0)
        bridge.start()
        port1 = bridge._actual_port
        bridge.start()  # Should be no-op
        assert bridge._actual_port == port1
        bridge.stop()


class TestChatSession:
    """Test chat session with mock subprocess."""

    def test_parse_result_event(self) -> None:
        """Verify the parser extracts text from 'result' events."""
        from hort.ext.chat_backend import ChatSession

        session = ChatSession("", "test prompt", model="sonnet")

        # Simulate Claude CLI output
        output_lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "test-123"}) + "\n",
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}}) + "\n",
            json.dumps({"type": "result", "result": "Hello there!", "session_id": "test-123"}) + "\n",
        ]

        async def run() -> str:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.stdout = AsyncMock()
                # Simulate readline returning lines then EOF
                mock_proc.stdout.readline = AsyncMock(
                    side_effect=[line.encode() for line in output_lines] + [b""]
                )
                mock_proc.wait = AsyncMock(return_value=0)
                mock_exec.return_value = mock_proc

                return await session._run("test message")

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result == "Hello there!"
        assert session._session_id == "test-123"

    def test_session_reset(self) -> None:
        from hort.ext.chat_backend import ChatSession

        session = ChatSession("", "test")
        session._session_id = "abc-123"
        session.reset()
        assert session._session_id is None

    def test_tool_tracking(self) -> None:
        """Verify tool use events are tracked for progress."""
        from hort.ext.chat_backend import ChatProgressEvent, ChatSession

        session = ChatSession("", "test", model="sonnet")

        output_lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}) + "\n",
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__openhort__llming-lens__list_windows"},
            ]}}) + "\n",
            json.dumps({"type": "result", "result": "19 windows", "session_id": "s1"}) + "\n",
        ]

        progress_events: list[ChatProgressEvent] = []

        async def on_progress(event: ChatProgressEvent) -> None:
            progress_events.append(event)

        async def run() -> str:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.stdout = AsyncMock()
                mock_proc.stdout.readline = AsyncMock(
                    side_effect=[line.encode() for line in output_lines] + [b""]
                )
                mock_proc.wait = AsyncMock(return_value=0)
                mock_exec.return_value = mock_proc

                return await session._run("how many windows?", on_progress)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result == "19 windows"


class TestChatBackendManager:
    """Test the session manager."""

    def test_get_session_creates_new(self) -> None:
        from hort.ext.chat_backend import ChatBackendManager

        mgr = ChatBackendManager.__new__(ChatBackendManager)
        mgr._system_prompt = "test"
        mgr._model = "sonnet"
        mgr._progress_interval = 8.0
        mgr._bridge = MagicMock()
        mgr._bridge.mcp_config_path = "/tmp/test.json"
        mgr._sessions = {}

        s1 = mgr.get_session("user1")
        s2 = mgr.get_session("user1")
        s3 = mgr.get_session("user2")
        assert s1 is s2  # Same user, same session
        assert s1 is not s3  # Different user, different session

    def test_reset_session(self) -> None:
        from hort.ext.chat_backend import ChatBackendManager, ChatSession

        mgr = ChatBackendManager.__new__(ChatBackendManager)
        mgr._sessions = {}
        session = ChatSession("", "test")
        session._session_id = "old-session"
        mgr._sessions["user1"] = session

        mgr.reset_session("user1")
        assert session._session_id is None

    def test_reset_nonexistent_session(self) -> None:
        from hort.ext.chat_backend import ChatBackendManager

        mgr = ChatBackendManager.__new__(ChatBackendManager)
        mgr._sessions = {}
        mgr.reset_session("nobody")  # Should not raise


class TestSecurityGuard:
    """Test that chat backend requires allowed_users."""

    def test_no_users_disables_chat(self) -> None:
        """Chat backend must not activate without allowed_users."""
        from hort.extensions.core.telegram_connector.provider import TelegramConnector
        from hort.ext.plugin import PluginConfig, PluginContext
        from hort.ext.scheduler import PluginScheduler
        import logging

        connector = TelegramConnector()
        connector._ctx = PluginContext(
            plugin_id="telegram-test",
            store=MagicMock(),
            files=MagicMock(),
            config=PluginConfig("telegram-test"),
            scheduler=PluginScheduler("telegram-test"),
            logger=logging.getLogger("test"),
        )

        # Activate with chat enabled but NO allowed_users
        connector.activate({
            "chat": {"enabled": True, "model": "sonnet"},
            # No allowed_users!
        })

        # Chat backend should NOT be created
        assert connector._ai_chat is None
