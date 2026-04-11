"""Tests for ClaudeCodePlugin — activation, status, envoy config loading."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llmings.core.claude_code.provider import ClaudeCodePlugin


@pytest.fixture
def plugin():
    """Create a ClaudeCodePlugin with minimal Llming context."""
    import logging
    p = ClaudeCodePlugin()
    p._instance_name = "claude-code"
    p._class_name = "claude-code"
    p._store = MagicMock()
    p._files = MagicMock()
    p._scheduler = MagicMock()
    p._logger = logging.getLogger("test.claude-code")
    p._chat_mgr = None
    p._started = False
    p._config = {}
    return p


def test_activate_stores_config(plugin):
    plugin.activate({"model": "claude-sonnet-4-6", "credentials": "keychain"})
    assert plugin._config["model"] == "claude-sonnet-4-6"
    assert plugin._config["credentials"] == "keychain"


def test_status_before_start(plugin):
    plugin.activate({})
    status = plugin.get_pulse()
    assert status["started"] is False
    assert status["alive"] is False
    assert status["active_sessions"] == 0


def test_get_mcp_tools(plugin):
    plugin.activate({})
    tools = plugin.get_mcp_tools()
    names = [t.name for t in tools]
    assert "send_message" in names
    assert "get_session_status" in names
    assert "reset_session" in names


def test_chat_never_crashes(plugin):
    """Chat should always return a string, never raise."""
    plugin.activate({})
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        plugin.chat("test-session", "Say just 'ok'")
    )
    assert isinstance(result, str)
    assert len(result) > 0


@patch("hort.hort_config.get_hort_config")
@patch("hort.agent.get_agent_config")
@patch("hort.ext.chat_backend.ChatBackendManager")
def test_ensure_started_reads_envoy_config(mock_backend, mock_agent_cfg, mock_hort_cfg, plugin):
    """Envoy container config from YAML should be applied to AgentConfig."""
    from hort.hort_config import HortConfig, LlmingConfig

    # Setup YAML config with envoy
    hort_cfg = HortConfig()
    hort_cfg.llmings["claude"] = LlmingConfig(
        name="claude",
        type="openhort/claude-code",
        config={"model": "claude-sonnet-4-6"},
        envoy={"container": {"image": "my-custom-image", "memory": "4g", "cpus": 4}},
    )
    mock_hort_cfg.return_value = hort_cfg

    # Setup agent config mock
    from hort.agent import AgentConfig
    agent_cfg = AgentConfig()
    mock_agent_cfg.return_value = agent_cfg

    # Mock ChatBackendManager
    mock_mgr = MagicMock()
    mock_mgr.alive = True
    mock_backend.return_value = mock_mgr

    plugin.activate({"model": "claude-sonnet-4-6"})
    plugin._ensure_started()

    # Verify ChatBackendManager was created with envoy overrides
    assert mock_backend.called
    call_kwargs = mock_backend.call_args
    passed_cfg = call_kwargs.kwargs.get("agent_cfg") or call_kwargs[1].get("agent_cfg")
    assert passed_cfg.image == "my-custom-image"
    assert passed_cfg.memory == "4g"
    assert passed_cfg.cpus == 4
    assert passed_cfg.container is True


def test_deactivate_stops_backend(plugin):
    plugin.activate({})
    mock_mgr = MagicMock()
    plugin._chat_mgr = mock_mgr
    plugin._started = True
    plugin.deactivate()
    mock_mgr.stop.assert_called_once()
    assert plugin._started is False
