"""Tests for Hort Chief — /horts command and MCP tools."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from hort.extensions.core.hort_chief.provider import HortChief


@pytest.fixture
def chief():
    from hort.ext.plugin import PluginContext
    p = HortChief()
    p._ctx = PluginContext(
        plugin_id="hort-chief",
        store=MagicMock(),
        files=MagicMock(),
        config={},
        scheduler=MagicMock(),
        logger=logging.getLogger("test.hort-chief"),
    )
    p.activate({})
    return p


def test_connector_commands_registered(chief):
    cmds = chief.get_connector_commands()
    assert len(cmds) == 1
    assert cmds[0].name == "horts"
    assert cmds[0].plugin_id == "hort-chief"


def test_mcp_tools_registered(chief):
    tools = chief.get_mcp_tools()
    names = [t["name"] for t in tools]
    assert "hort_overview" in names
    assert "list_containers" in names
    assert "list_sessions" in names


@patch("hort.hort_config.get_hort_config")
def test_admin_check_denies_unknown_user(mock_cfg, chief):
    from hort.hort_config import HortConfig
    mock_cfg.return_value = HortConfig()
    msg = MagicMock()
    msg.username = "unknown_user"
    assert chief._is_admin(msg) is False


@patch("hort.hort_config.get_hort_config")
def test_admin_check_allows_admin_user(mock_cfg, chief):
    from hort.hort_config import HortConfig, UserConfig, GroupConfig
    cfg = HortConfig()
    cfg.users["michael"] = UserConfig(
        name="michael", groups=["owner"], match={"telegram": "alice_dev"}
    )
    cfg.groups["owner"] = GroupConfig(
        name="owner", wire={"allow_admin": True}
    )
    mock_cfg.return_value = cfg

    msg = MagicMock()
    msg.username = "alice_dev"
    assert chief._is_admin(msg) is True


@patch("hort.hort_config.get_hort_config")
def test_admin_check_denies_non_admin_group(mock_cfg, chief):
    from hort.hort_config import HortConfig, UserConfig, GroupConfig
    cfg = HortConfig()
    cfg.users["sarah"] = UserConfig(
        name="sarah", groups=["viewer"], match={"telegram": "sarah_dev"}
    )
    cfg.groups["viewer"] = GroupConfig(
        name="viewer", wire={"allow_admin": False}
    )
    mock_cfg.return_value = cfg

    msg = MagicMock()
    msg.username = "sarah_dev"
    assert chief._is_admin(msg) is False


@patch("hort.extensions.core.hort_chief.provider.HortChief._get_containers")
@patch("hort.extensions.core.hort_chief.provider.HortChief._get_sessions")
@patch("hort.hort_config.get_hort_config")
def test_build_overview_content(mock_cfg, mock_sessions, mock_containers, chief):
    from hort.hort_config import HortConfig
    cfg = HortConfig(name="Test Mac")
    mock_cfg.return_value = cfg

    mock_containers.return_value = [
        {"name": "ohsb-abc123def456", "status": "Up 5 minutes", "image": "openhort-claude-code"}
    ]
    mock_sessions.return_value = [
        {"id": "abc12345...", "type": "lan", "ip": "127.0.0.1"}
    ]

    text = chief._build_overview()
    assert "Test Mac" in text
    assert "abc123def456" in text
    assert "openhort-claude-code" in text
    assert "lan" in text
    assert "/horts" in text  # hint for subcommand


@pytest.mark.asyncio
async def test_handle_horts_command_denied(chief):
    from hort.ext.connectors import ConnectorResponse
    msg = MagicMock()
    msg.username = "unknown"

    with patch.object(chief, "_is_admin", return_value=False):
        result = await chief.handle_connector_command("horts", msg, MagicMock())
    assert "Permission denied" in result.text


@pytest.mark.asyncio
async def test_handle_horts_command_allowed(chief):
    msg = MagicMock()
    msg.username = "alice_dev"
    msg.command_args = ""  # no subcommand — show overview

    with patch.object(chief, "_is_admin", return_value=True), \
         patch.object(chief, "_get_containers", return_value=[
             {"name": "ohsb-test123", "status": "Up 5m", "image": "test-img"}
         ]), \
         patch.object(chief, "_get_sessions", return_value=[]), \
         patch("hort.hort_config.get_hort_config") as mock_cfg:
        from hort.hort_config import HortConfig
        mock_cfg.return_value = HortConfig(name="Test Hort")
        result = await chief.handle_connector_command("horts", msg, MagicMock())
    assert "Test Hort" in result.text
    assert "test123" in result.text
    assert result.buttons is not None


@pytest.mark.asyncio
async def test_handle_horts_command_error_safe(chief):
    """Errors never leak to user."""
    msg = MagicMock()

    with patch.object(chief, "_is_admin", return_value=True), \
         patch.object(chief, "_build_overview", side_effect=RuntimeError("boom")):
        result = await chief.handle_connector_command("horts", msg, MagicMock())
    assert "Something went wrong" in result.text
    assert "boom" not in result.text
