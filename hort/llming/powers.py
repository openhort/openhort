"""Power definitions — what a llming can DO.

Three power types, all returned by a single ``get_powers()`` method:

- **MCP** — JSON-RPC tools for AI agents (structured I/O)
- **COMMAND** — Slash commands for humans via Telegram/Wire (text/HTML response)
- **ACTION** — Publishable Python functions with Pydantic models (typed I/O)

Actions are auto-exposed as MCP tools (JSON Schema from Pydantic) and
REST endpoints (``POST /api/llmings/{instance}/actions/{name}``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Type

from pydantic import BaseModel


class PowerType(str, Enum):
    """Type of power a llming provides."""

    MCP = "mcp"          # MCP tools (JSON-RPC, structured I/O)
    COMMAND = "command"   # Slash commands (/cpu, /horts — text/HTML response)
    ACTION = "action"     # Publishable Python functions (Pydantic in/out)


@dataclass
class Power:
    """A single capability exposed by a llming.

    Examples::

        # MCP tool — AI agents call this
        Power(
            name="get_cpu",
            type=PowerType.MCP,
            description="Get current CPU usage",
            input_schema={"type": "object", "properties": {}},
        )

        # Slash command — humans type /cpu in Telegram
        Power(
            name="cpu",
            type=PowerType.COMMAND,
            description="Show CPU usage",
            input_schema={"type": "object", "properties": {
                "args": {"type": "string", "default": ""}
            }},
            admin_only=True,
        )

        # Action — typed Python function, auto-exposed as MCP + REST
        Power(
            name="get_cpu_status",
            type=PowerType.ACTION,
            description="Get CPU metrics",
            input_schema=CpuRequest,
            output_schema=CpuResponse,
        )
    """

    name: str
    type: PowerType
    description: str
    input_schema: dict[str, Any] | Type[BaseModel] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    output_schema: dict[str, Any] | Type[BaseModel] | None = None
    handler: Callable[..., Any] | None = None
    admin_only: bool = False

    def to_mcp_tool_def(self) -> dict[str, Any]:
        """Convert to MCP tool definition format.

        For ACTION powers, generates JSON Schema from the Pydantic model.
        """
        schema: dict[str, Any]
        if isinstance(self.input_schema, type) and issubclass(
            self.input_schema, BaseModel
        ):
            schema = self.input_schema.model_json_schema()
        elif isinstance(self.input_schema, dict):
            schema = self.input_schema
        else:
            schema = {"type": "object", "properties": {}}

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema,
        }

    def to_connector_command(self) -> dict[str, Any]:
        """Convert to connector command format for slash command routing."""
        return {
            "command": self.name,
            "description": self.description,
            "admin_only": self.admin_only,
        }
