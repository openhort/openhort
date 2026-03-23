"""Tests for plugin mixins — IntentMixin, MCPMixin, DocumentMixin."""

from __future__ import annotations

import pytest

from hort.ext.documents import DocumentMixin
from hort.ext.intents import IntentMixin
from hort.ext.mcp import MCPMixin, MCPToolResult


class TestIntentMixin:
    def test_default_get_intent_handlers(self) -> None:
        mixin = IntentMixin()
        assert mixin.get_intent_handlers() == []


class TestMCPMixin:
    def test_default_get_mcp_tools(self) -> None:
        mixin = MCPMixin()
        assert mixin.get_mcp_tools() == []

    async def test_default_execute_returns_error(self) -> None:
        mixin = MCPMixin()
        result = await mixin.execute_mcp_tool("unknown", {})
        assert isinstance(result, MCPToolResult)
        assert result.is_error is True


class TestDocumentMixin:
    def test_default_get_documents(self) -> None:
        mixin = DocumentMixin()
        assert mixin.get_documents() == []
