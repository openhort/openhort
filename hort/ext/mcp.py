"""MCP data types — tool definitions and results.

These types are used by the MCP bridge and the Llming compat layer.
The MCPMixin class has been removed — all llmings use Llming.get_powers().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPToolDef:
    """Definition of an MCP tool provided by a llming."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPToolResult:
    """Result from executing an MCP tool."""

    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
