"""Tests for the chat backend — agent config, container isolation, and E2E flow.

Tests the full chain: AgentConfig → ChatBackendManager → ChatSession → Claude Code CLI.
Verifies that:
- Agent config defaults to container=True, dangerous_mode=False
- Container sessions use hardened Docker with --allowedTools (not --dangerously-skip-permissions)
- MCP bridge URL is rewritten for container access
- E2E: Telegram message → container Claude Code → MCP tool (CPU/RAM) → response
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hort.agent import AgentConfig, DEFAULT_ALLOWED_TOOLS, get_agent_config


# ── AgentConfig ───────────────────────────────────────────────────


class TestAgentConfig:
    """Test the shared agent configuration model."""

    def test_secure_defaults(self) -> None:
        """Default config: container=True, dangerous_mode=False."""
        cfg = AgentConfig()
        assert cfg.container is True
        assert cfg.dangerous_mode is False
        assert cfg.provider == "claude-code"
        assert cfg.memory == "2g"
        assert cfg.cpus == 2
        assert cfg.allowed_tools == list(DEFAULT_ALLOWED_TOOLS)

    def test_allowed_tools_default(self) -> None:
        """Default tools include file ops, Bash, and MCP wildcard."""
        cfg = AgentConfig()
        assert "Bash" in cfg.allowed_tools
        assert "Read" in cfg.allowed_tools
        assert "mcp__openhort__*" in cfg.allowed_tools

    def test_custom_config(self) -> None:
        cfg = AgentConfig(
            model="claude-sonnet-4-6",
            container=False,
            dangerous_mode=True,
            memory="4g",
            cpus=4,
            allowed_tools=["Bash", "Read"],
        )
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.container is False
        assert cfg.dangerous_mode is True
        assert cfg.memory == "4g"
        assert cfg.allowed_tools == ["Bash", "Read"]

    def test_get_agent_config_defaults(self) -> None:
        """get_agent_config() returns secure defaults when no config file."""
        with patch("hort.config.get_store") as mock_store:
            mock_store.return_value.get.return_value = {}
            cfg = get_agent_config()
            assert cfg.container is True
            assert cfg.dangerous_mode is False

    def test_get_agent_config_from_yaml(self) -> None:
        """get_agent_config() reads from hort-config.yaml."""
        with patch("hort.config.get_store") as mock_store:
            mock_store.return_value.get.return_value = {
                "model": "claude-sonnet-4-6",
                "container": True,
                "dangerous_mode": False,
                "memory": "4g",
            }
            cfg = get_agent_config()
            assert cfg.model == "claude-sonnet-4-6"
            assert cfg.memory == "4g"
            assert cfg.container is True

    def test_model_copy_override(self) -> None:
        """Connectors can override individual fields via model_copy."""
        base = AgentConfig(model="opus")
        override = base.model_copy(update={"model": "sonnet"})
        assert override.model == "sonnet"
        assert override.container is True  # preserved


# ── Claude command building ───────────────────────────────────────


class TestBuildClaudeCmd:
    """Test that the claude CLI command is built correctly."""

    def test_default_uses_allowed_tools(self) -> None:
        """Default: --allowedTools instead of --dangerously-skip-permissions."""
        from hort.ext.chat_backend import _build_claude_cmd

        cfg = AgentConfig()
        cmd = _build_claude_cmd(cfg, "/tmp/mcp.json", "prompt", None, "hello")

        assert "--dangerously-skip-permissions" not in cmd
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        tools_str = cmd[idx + 1]
        assert "Bash" in tools_str
        assert "Read" in tools_str
        assert "mcp__openhort__*" in tools_str

    def test_dangerous_mode_uses_flag(self) -> None:
        """When dangerous_mode=True, uses --dangerously-skip-permissions."""
        from hort.ext.chat_backend import _build_claude_cmd

        cfg = AgentConfig(dangerous_mode=True)
        cmd = _build_claude_cmd(cfg, "/tmp/mcp.json", "prompt", None, "hello")

        assert "--dangerously-skip-permissions" in cmd
        assert "--allowedTools" not in cmd

    def test_container_mode_adds_bare(self) -> None:
        """Container mode adds --bare flag."""
        from hort.ext.chat_backend import _build_claude_cmd

        cfg = AgentConfig(container=True)
        cmd = _build_claude_cmd(cfg, "", "", None, "hi")
        assert "--bare" in cmd

    def test_host_mode_no_bare(self) -> None:
        """Host mode does not add --bare."""
        from hort.ext.chat_backend import _build_claude_cmd

        cfg = AgentConfig(container=False)
        cmd = _build_claude_cmd(cfg, "", "", None, "hi")
        assert "--bare" not in cmd

    def test_resume_session(self) -> None:
        """Existing session_id triggers --resume."""
        from hort.ext.chat_backend import _build_claude_cmd

        cfg = AgentConfig()
        cmd = _build_claude_cmd(cfg, "", "prompt", "sess-123", "hi")
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "sess-123"

    def test_model_passed(self) -> None:
        from hort.ext.chat_backend import _build_claude_cmd

        cfg = AgentConfig(model="claude-sonnet-4-6")
        cmd = _build_claude_cmd(cfg, "", "", None, "hi")
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-6"

    def test_budget_passed(self) -> None:
        from hort.ext.chat_backend import _build_claude_cmd

        cfg = AgentConfig(max_budget_usd=5.0)
        cmd = _build_claude_cmd(cfg, "", "", None, "hi")
        assert "--max-budget-usd" in cmd


# ── MCPBridgeProcess ──────────────────────────────────────────────


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
            with open(bridge.mcp_config_path) as f:
                config = json.load(f)
            assert "mcpServers" in config
            assert "openhort" in config["mcpServers"]
            assert "sse" in config["mcpServers"]["openhort"]["type"]
        finally:
            bridge.stop()
        assert not bridge.alive
        assert not bridge.mcp_config_path

    def test_container_url(self) -> None:
        from hort.ext.chat_backend import MCPBridgeProcess

        bridge = MCPBridgeProcess(port=0)
        bridge._actual_port = 12345
        assert bridge.container_url() == "http://host.docker.internal:12345/sse"

    def test_idempotent_start(self) -> None:
        from hort.ext.chat_backend import MCPBridgeProcess

        bridge = MCPBridgeProcess(port=0)
        bridge.start()
        port1 = bridge._actual_port
        bridge.start()  # Should be no-op
        assert bridge._actual_port == port1
        bridge.stop()


# ── ChatSession ───────────────────────────────────────────────────


class TestChatSession:
    """Test chat session with mock subprocess."""

    def test_parse_result_event(self) -> None:
        """Verify the parser extracts text from 'result' events."""
        from hort.ext.chat_backend import ChatSession

        session = ChatSession(
            agent_cfg=AgentConfig(container=False),
            mcp_config_path="",
            system_prompt="test prompt",
        )

        output_lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "test-123"}) + "\n",
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}}) + "\n",
            json.dumps({"type": "result", "result": "Hello there!", "session_id": "test-123"}) + "\n",
        ]

        async def run() -> str:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.stdout = AsyncMock()
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

        session = ChatSession(
            agent_cfg=AgentConfig(container=False),
            mcp_config_path="",
            system_prompt="test",
        )
        session._session_id = "abc-123"
        session.reset()
        assert session._session_id is None

    def test_container_session_uses_exec_async(self) -> None:
        """When container_session is set, uses exec_async instead of subprocess."""
        from hort.ext.chat_backend import ChatSession

        mock_container = MagicMock()
        mock_proc = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=[
            json.dumps({"type": "result", "result": "container response"}).encode() + b"\n",
            b"",
        ])
        mock_proc.wait = AsyncMock(return_value=0)
        mock_container.exec_async = AsyncMock(return_value=mock_proc)

        session = ChatSession(
            agent_cfg=AgentConfig(),
            mcp_config_path="/workspace/.claude-mcp.json",
            system_prompt="test",
            container_session=mock_container,
        )

        async def run() -> str:
            return await session._run("test")

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result == "container response"
        mock_container.exec_async.assert_called_once()

        # Verify the command passed to exec_async
        call_args = mock_container.exec_async.call_args[0][0]
        assert call_args[0] == "claude"
        assert "--bare" in call_args
        assert "--allowedTools" in call_args
        assert "--dangerously-skip-permissions" not in call_args


# ── ChatBackendManager ────────────────────────────────────────────


class TestChatBackendManager:
    """Test the session manager."""

    def test_get_session_creates_new(self) -> None:
        from hort.ext.chat_backend import ChatBackendManager

        mgr = ChatBackendManager.__new__(ChatBackendManager)
        mgr._agent_cfg = AgentConfig(container=False)
        mgr._system_prompt = "test"
        mgr._bridge = MagicMock()
        mgr._bridge.mcp_config_path = "/tmp/test.json"
        mgr._sessions = {}
        mgr._container_sessions = {}
        mgr._session_manager = None

        s1 = mgr.get_session("user1")
        s2 = mgr.get_session("user1")
        s3 = mgr.get_session("user2")
        assert s1 is s2
        assert s1 is not s3

    def test_reset_session(self) -> None:
        from hort.ext.chat_backend import ChatBackendManager, ChatSession

        mgr = ChatBackendManager.__new__(ChatBackendManager)
        mgr._sessions = {}
        session = ChatSession(
            agent_cfg=AgentConfig(container=False),
            mcp_config_path="",
            system_prompt="test",
        )
        session._session_id = "old-session"
        mgr._sessions["user1"] = session

        mgr.reset_session("user1")
        assert session._session_id is None

    def test_container_session_created(self) -> None:
        """When container=True, a sandbox Session is created per user."""
        from hort.ext.chat_backend import ChatBackendManager

        mgr = ChatBackendManager.__new__(ChatBackendManager)
        mgr._agent_cfg = AgentConfig(container=True)
        mgr._system_prompt = "test"
        mgr._bridge = MagicMock()
        mgr._bridge.mcp_config_path = "/tmp/test.json"
        mgr._bridge.container_url.return_value = "http://host.docker.internal:9999/sse"
        mgr._sessions = {}
        mgr._container_sessions = {}

        mock_sandbox_session = MagicMock()
        mock_sandbox_session.id = "test-id"

        mock_manager = MagicMock()
        mock_manager.create.return_value = mock_sandbox_session
        mgr._session_manager = mock_manager

        session = mgr.get_session("user1")

        # Verify container was created and started
        mock_manager.create.assert_called_once()
        mock_sandbox_session.start.assert_called_once()

        # Verify MCP config was written inside container
        mock_sandbox_session.write_file.assert_called_once()
        write_args = mock_sandbox_session.write_file.call_args
        assert write_args[0][0] == "/workspace/.claude-mcp.json"
        mcp_cfg = json.loads(write_args[0][1])
        assert "host.docker.internal" in mcp_cfg["mcpServers"]["openhort"]["url"]

    def test_stop_destroys_containers(self) -> None:
        """stop() destroys all container sessions."""
        from hort.ext.chat_backend import ChatBackendManager

        mgr = ChatBackendManager.__new__(ChatBackendManager)
        mgr._bridge = MagicMock()
        mgr._sessions = {}
        mock_container = MagicMock()
        mgr._container_sessions = {"user1": mock_container}

        mgr.stop()
        mock_container.destroy.assert_called_once()
        assert len(mgr._container_sessions) == 0


# ── Security guard ────────────────────────────────────────────────


class TestSecurityGuard:
    """Test that chat backend requires allowed_users."""

    def test_no_users_disables_chat(self) -> None:
        """Chat backend must not activate without allowed_users."""
        from llmings.core.telegram_connector.telegram_connector import TelegramConnector
        from hort.ext.scheduler import PluginScheduler
        import logging

        connector = TelegramConnector()
        connector._instance_name = "telegram-test"
        connector._class_name = "telegram-test"
        connector._store = MagicMock()
        connector._files = MagicMock()
        connector._scheduler = PluginScheduler("telegram-test")
        connector._logger = logging.getLogger("test")
        connector._config = {}

        connector.activate({
            "chat": {"enabled": True, "model": "sonnet"},
        })
        assert connector._ai_chat is None


# ── E2E Simulation ────────────────────────────────────────────────


class TestE2ETelegramFlow:
    """Simulate the full Telegram → container Claude Code → MCP → response flow.

    This test verifies the complete message path without real Docker or
    Claude Code by mocking at the subprocess/Docker boundary.
    """

    def test_telegram_chat_cpu_ram_check(self) -> None:
        """Simulate: user sends 'check CPU and RAM' via Telegram.

        Flow:
        1. Telegram connector receives message
        2. ChatBackendManager routes to ChatSession
        3. ChatSession builds claude command with --allowedTools
        4. Command runs in container via exec_async
        5. Claude calls get_system_metrics MCP tool
        6. Response returned to Telegram
        """
        from hort.ext.chat_backend import ChatBackendManager, ChatSession

        # Build the stream-json output that Claude Code would produce
        # when asked to check CPU and RAM
        claude_output = [
            json.dumps({
                "type": "system", "subtype": "init",
                "session_id": "e2e-test-001",
            }) + "\n",
            json.dumps({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use",
                    "name": "mcp__openhort__llming-lens__get_system_metrics",
                    "id": "tool-1",
                    "input": {},
                }]},
            }) + "\n",
            json.dumps({
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": [{"type": "text", "text": json.dumps({
                    "cpu_percent": 23.5,
                    "memory_percent": 67.2,
                    "memory_used_gb": 10.8,
                    "memory_total_gb": 16.0,
                })}],
            }) + "\n",
            json.dumps({
                "type": "result",
                "result": "CPU is at 23.5% and RAM usage is 67.2% (10.8 GB out of 16 GB).",
                "session_id": "e2e-test-001",
            }) + "\n",
        ]

        # Mock container session (docker exec)
        mock_container = MagicMock()
        mock_proc = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.readline = AsyncMock(
            side_effect=[line.encode() for line in claude_output] + [b""]
        )
        mock_proc.wait = AsyncMock(return_value=0)
        mock_container.exec_async = AsyncMock(return_value=mock_proc)

        # Create session with container backend
        agent_cfg = AgentConfig(container=True, model="claude-sonnet-4-6")
        session = ChatSession(
            agent_cfg=agent_cfg,
            mcp_config_path="/workspace/.claude-mcp.json",
            system_prompt="You are a desktop assistant.",
            container_session=mock_container,
        )

        # Simulate sending the message
        async def run() -> str:
            return await session.send("check CPU and RAM")

        result = asyncio.get_event_loop().run_until_complete(run())

        # Verify response
        assert "23.5%" in result
        assert "67.2%" in result
        assert "10.8" in result

        # Verify container exec was called
        mock_container.exec_async.assert_called_once()
        cmd = mock_container.exec_async.call_args[0][0]

        # Verify security: no dangerous mode, uses allowedTools
        assert "--dangerously-skip-permissions" not in cmd
        assert "--allowedTools" in cmd
        assert "--bare" in cmd  # container mode
        assert "--model" in cmd

        # Verify the allowed tools include MCP wildcard
        idx = cmd.index("--allowedTools")
        tools = cmd[idx + 1]
        assert "mcp__openhort__*" in tools
        assert "Bash" in tools

    def test_telegram_chat_host_mode_fallback(self) -> None:
        """When container=False, Claude runs as direct subprocess."""
        from hort.ext.chat_backend import ChatSession

        agent_cfg = AgentConfig(container=False)

        claude_output = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "host-1"}) + "\n",
            json.dumps({"type": "result", "result": "Hello from host mode.", "session_id": "host-1"}) + "\n",
        ]

        session = ChatSession(
            agent_cfg=agent_cfg,
            mcp_config_path="/tmp/mcp.json",
            system_prompt="test",
            container_session=None,
        )

        async def run() -> str:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.stdout = AsyncMock()
                mock_proc.stdout.readline = AsyncMock(
                    side_effect=[line.encode() for line in claude_output] + [b""]
                )
                mock_proc.wait = AsyncMock(return_value=0)
                mock_exec.return_value = mock_proc
                return await session._run("hello")

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result == "Hello from host mode."

    def test_connector_reads_shared_agent_config(self) -> None:
        """Telegram connector reads agent config from hort-config.yaml."""
        from llmings.core.telegram_connector.telegram_connector import TelegramConnector
        from hort.ext.scheduler import PluginScheduler
        import logging

        connector = TelegramConnector()
        connector._instance_name = "telegram-test"
        connector._class_name = "telegram-test"
        connector._store = MagicMock()
        connector._files = MagicMock()
        connector._scheduler = PluginScheduler("telegram-test")
        connector._logger = logging.getLogger("test")
        connector._config = {}

        with patch("hort.config.get_store") as mock_store:
            mock_store.return_value.get.return_value = {
                "model": "claude-sonnet-4-6",
                "container": True,
                "dangerous_mode": False,
            }
            connector.activate({
                "allowed_users": ["testuser"],
                "chat": {"enabled": True},
            })

        assert connector._ai_chat is not None
        assert connector._ai_chat.agent_cfg.container is True
        assert connector._ai_chat.agent_cfg.dangerous_mode is False
        assert connector._ai_chat.agent_cfg.model == "claude-sonnet-4-6"

    def test_connector_overrides_model(self) -> None:
        """Connector-level model override takes precedence."""
        from llmings.core.telegram_connector.telegram_connector import TelegramConnector
        from hort.ext.scheduler import PluginScheduler
        import logging

        connector = TelegramConnector()
        connector._instance_name = "telegram-test"
        connector._class_name = "telegram-test"
        connector._store = MagicMock()
        connector._files = MagicMock()
        connector._scheduler = PluginScheduler("telegram-test")
        connector._logger = logging.getLogger("test")
        connector._config = {}

        with patch("hort.config.get_store") as mock_store:
            mock_store.return_value.get.return_value = {
                "model": "opus",
                "container": True,
            }
            connector.activate({
                "allowed_users": ["testuser"],
                "chat": {"enabled": True, "model": "haiku"},
            })

        assert connector._ai_chat.agent_cfg.model == "haiku"
