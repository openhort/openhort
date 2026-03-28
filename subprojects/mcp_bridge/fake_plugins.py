"""Fake MCPMixin plugins for testing the bridge — no dependency on hort.ext."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPToolDef:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPToolResult:
    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False


class FakeMemoryPlugin:
    """Simulates an in-process memory/notes plugin with MCP tools."""

    plugin_id = "memory"

    def __init__(self) -> None:
        self._notes: dict[str, str] = {}

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="save_note",
                description="Save a named note",
                input_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Note name"},
                        "text": {"type": "string", "description": "Note content"},
                    },
                    "required": ["key", "text"],
                },
            ),
            MCPToolDef(
                name="get_note",
                description="Retrieve a saved note by name",
                input_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Note name"},
                    },
                    "required": ["key"],
                },
            ),
            MCPToolDef(
                name="list_notes",
                description="List all saved note names",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        if tool_name == "save_note":
            self._notes[arguments["key"]] = arguments["text"]
            return MCPToolResult(
                content=[{"type": "text", "text": f"Saved note '{arguments['key']}'"}]
            )
        if tool_name == "get_note":
            key = arguments["key"]
            text = self._notes.get(key)
            if text is None:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Note '{key}' not found"}],
                    is_error=True,
                )
            return MCPToolResult(
                content=[{"type": "text", "text": text}]
            )
        if tool_name == "list_notes":
            keys = sorted(self._notes.keys())
            return MCPToolResult(
                content=[{"type": "text", "text": ", ".join(keys) if keys else "(empty)"}]
            )
        return MCPToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            is_error=True,
        )


class FakeCalculatorPlugin:
    """Simulates an in-process calculator plugin with MCP tools."""

    plugin_id = "calc"

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="add",
                description="Add two numbers",
                input_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            ),
            MCPToolDef(
                name="multiply",
                description="Multiply two numbers",
                input_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        if tool_name == "add":
            return MCPToolResult(
                content=[{"type": "text", "text": str(a + b)}]
            )
        if tool_name == "multiply":
            return MCPToolResult(
                content=[{"type": "text", "text": str(a * b)}]
            )
        return MCPToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            is_error=True,
        )


class FakeErrorPlugin:
    """Plugin whose tool execution raises an exception — for error handling tests."""

    plugin_id = "buggy"

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="crash",
                description="This tool always crashes",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        raise RuntimeError("intentional crash for testing")
