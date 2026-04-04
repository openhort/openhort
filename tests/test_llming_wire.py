"""Tests for the llming-wire chat extension."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hort.extensions.core.llming_wire.provider import (
    LlmingWire,
    _extract_buttons,
    _strip_button_lines,
)


# ── Button extraction ─────────────────────────────────────────────


class TestButtonExtraction:
    def test_numbered_options(self) -> None:
        text = "Which approach?\n1. Fix the bug\n2. Write tests\n3. Refactor"
        buttons = _extract_buttons(text)
        assert len(buttons) == 3
        assert buttons[0]["label"] == "1. Fix the bug"
        assert buttons[2]["id"] == "3"

    def test_single_option_not_buttons(self) -> None:
        text = "1. Just one option"
        buttons = _extract_buttons(text)
        assert buttons == []

    def test_too_many_not_buttons(self) -> None:
        text = "\n".join(f"{i}. Option {i}" for i in range(1, 15))
        buttons = _extract_buttons(text)
        assert buttons == []

    def test_no_options(self) -> None:
        text = "Just a regular response with no numbered items."
        buttons = _extract_buttons(text)
        assert buttons == []

    def test_strip_button_lines(self) -> None:
        text = "Choose:\n1. Option A\n2. Option B\nDone."
        stripped = _strip_button_lines(text)
        assert "Option A" not in stripped
        assert "Done." in stripped


# ── Command handling ──────────────────────────────────────────────


class TestCommandHandling:
    @pytest.fixture()
    def wire(self) -> LlmingWire:
        from hort.ext.plugin import PluginConfig, PluginContext
        from hort.ext.scheduler import PluginScheduler
        import logging

        w = LlmingWire()
        w._ctx = PluginContext(
            plugin_id="llming-wire-test",
            store=MagicMock(),
            files=MagicMock(),
            config=PluginConfig("llming-wire-test"),
            scheduler=PluginScheduler("llming-wire-test"),
            logger=logging.getLogger("test.wire"),
        )
        w.activate({})
        return w

    def test_new_command(self, wire: LlmingWire) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            wire._handle_command("conv1", "new")
        )
        assert result is not None
        assert "New chat session" in result["text"]
        assert result["session_id"] is None

    def test_new_resets_session(self, wire: LlmingWire) -> None:
        mock_mgr = MagicMock()
        wire._chat_mgr = mock_mgr
        asyncio.get_event_loop().run_until_complete(
            wire._handle_command("conv1", "new")
        )
        mock_mgr.reset_session.assert_called_once_with("llming-wire:conv1")

    def test_help_command(self, wire: LlmingWire) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            wire._handle_command("conv1", "help")
        )
        assert result is not None
        assert "/new" in result["text"]

    def test_help_includes_registry_commands(self, wire: LlmingWire) -> None:
        """Help should include dynamically registered commands."""
        mock_cmd = MagicMock()
        mock_cmd.name = "cpu"
        mock_cmd.description = "Show CPU usage"
        mock_cmd.hidden = False

        mock_registry = MagicMock()
        mock_registry.get_all_commands.return_value = [mock_cmd]

        with patch("hort.plugins.get_command_registry", return_value=mock_registry):
            result = asyncio.get_event_loop().run_until_complete(
                wire._handle_command("conv1", "help")
            )
        assert "/cpu" in result["text"]
        assert "CPU usage" in result["text"]

    def test_unknown_command_returns_none(self, wire: LlmingWire) -> None:
        """Unknown commands return None (passed to AI)."""
        result = asyncio.get_event_loop().run_until_complete(
            wire._handle_command("conv1", "nonexistent_xyz")
        )
        assert result is None

    def test_registered_command_dispatched(self, wire: LlmingWire) -> None:
        """Commands from the shared registry are dispatched correctly."""
        from hort.ext.connectors import ConnectorResponse

        mock_response = ConnectorResponse(text="CPU: 15% (14 cores)")
        mock_registry = MagicMock()
        mock_registry.dispatch = AsyncMock(return_value=mock_response)

        with patch("hort.plugins.get_command_registry", return_value=mock_registry):
            result = asyncio.get_event_loop().run_until_complete(
                wire._handle_command("conv1", "cpu")
            )
        assert result is not None
        assert "CPU" in result["text"]
        mock_registry.dispatch.assert_called_once()

    def test_registry_not_available(self, wire: LlmingWire) -> None:
        """When registry isn't available, unknown commands pass through."""
        with patch("hort.plugins.get_command_registry", return_value=None):
            result = asyncio.get_event_loop().run_until_complete(
                wire._handle_command("conv1", "cpu")
            )
        assert result is None


# ── REST API ──────────────────────────────────────────────────────


class TestRESTAPI:
    @pytest.fixture()
    def wire(self) -> LlmingWire:
        from hort.ext.plugin import PluginConfig, PluginContext
        from hort.ext.scheduler import PluginScheduler
        import logging

        w = LlmingWire()
        w._ctx = PluginContext(
            plugin_id="llming-wire-test",
            store=MagicMock(),
            files=MagicMock(),
            config=PluginConfig("llming-wire-test"),
            scheduler=PluginScheduler("llming-wire-test"),
            logger=logging.getLogger("test.wire"),
        )
        w.activate({})
        return w

    def test_get_router(self, wire: LlmingWire) -> None:
        router = wire.get_router()
        assert router is not None
        # Should have routes for conversations and messages
        paths = [r.path for r in router.routes]
        assert "/conversations" in paths
        assert "/conversations/{cid}/messages" in paths

    def test_slash_command_intercepted(self, wire: LlmingWire) -> None:
        """Slash commands should be handled before reaching AI."""
        async def run():
            result = await wire._handle_command("test", "new")
            return result

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result is not None
        assert result["role"] == "assistant"


# ── Session resumption ────────────────────────────────────────────


class TestSessionResumption:
    @pytest.fixture()
    def wire(self) -> LlmingWire:
        from hort.ext.plugin import PluginConfig, PluginContext
        from hort.ext.scheduler import PluginScheduler
        import logging

        w = LlmingWire()
        w._ctx = PluginContext(
            plugin_id="llming-wire-test",
            store=MagicMock(),
            files=MagicMock(),
            config=PluginConfig("llming-wire-test"),
            scheduler=PluginScheduler("llming-wire-test"),
            logger=logging.getLogger("test.wire"),
        )
        w.activate({})
        return w

    def test_session_id_restored(self, wire: LlmingWire) -> None:
        """Client session_id should restore server session on reconnect."""
        mock_session = MagicMock()
        mock_session._session_id = None
        mock_session.send = AsyncMock(return_value="Hello!")

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = mock_session
        mock_mgr.alive = True
        wire._chat_mgr = mock_mgr

        async def run():
            return await wire._get_ai_response("conv1", "hi", client_session_id="saved-session-123")

        asyncio.get_event_loop().run_until_complete(run())
        assert mock_session._session_id == "saved-session-123"

    def test_session_id_not_overwritten(self, wire: LlmingWire) -> None:
        """If server already has a session, client's ID shouldn't overwrite it."""
        mock_session = MagicMock()
        mock_session._session_id = "server-session-456"
        mock_session.send = AsyncMock(return_value="Hi!")

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = mock_session
        mock_mgr.alive = True
        wire._chat_mgr = mock_mgr

        async def run():
            return await wire._get_ai_response("conv1", "hi", client_session_id="old-client-id")

        asyncio.get_event_loop().run_until_complete(run())
        assert mock_session._session_id == "server-session-456"
