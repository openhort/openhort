"""MCP integration — plugins provide tools for AI assistants.

Plugins that implement ``MCPMixin`` expose tools via the Model Context
Protocol. Tools are aggregated by the MCP server (``hort/mcp_server.py``)
and presented to the AI as a single endpoint.

Set ``"mcp": true`` in the manifest to enable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPToolDef:
    """Definition of an MCP tool provided by a plugin."""

    name: str  # globally unique tool name
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPToolResult:
    """Result from executing an MCP tool."""

    content: list[dict[str, Any]] = field(default_factory=list)  # MCP content blocks
    is_error: bool = False


class MCPMixin:
    """Mixin for plugins that expose MCP tools.

    Example::

        class MyPlugin(PluginBase, MCPMixin):
            def get_mcp_tools(self) -> list[MCPToolDef]:
                return [
                    MCPToolDef(
                        name="get_weather",
                        description="Get current weather for a location",
                        input_schema={
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "description": "City name"},
                            },
                            "required": ["city"],
                        },
                    ),
                ]

            async def execute_mcp_tool(self, tool_name: str, arguments: dict) -> MCPToolResult:
                if tool_name == "get_weather":
                    weather = self.fetch_weather(arguments["city"])
                    return MCPToolResult(
                        content=[{"type": "text", "text": f"Weather: {weather}"}]
                    )
                return MCPToolResult(
                    content=[{"type": "text", "text": "Unknown tool"}],
                    is_error=True,
                )
    """

    def get_mcp_tools(self) -> list[MCPToolDef]:
        """Return MCP tool definitions this plugin provides."""
        return []

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        """Execute an MCP tool call. Override in subclass."""
        return MCPToolResult(
            content=[{"type": "text", "text": f"Tool {tool_name} not implemented"}],
            is_error=True,
        )
