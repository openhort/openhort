"""Envoy control channel protocol — JSON-over-TCP messages.

All messages are newline-delimited JSON (one JSON object per line).
The control channel is bidirectional:

Host → Envoy:
    register_tools   — push current tool definitions
    tool_result       — response to a tool_call
    ping              — health check
    set_credential    — provision an in-memory credential
    request_local_tools — ask what tools the container provides
    call_local_tool   — invoke a container-local tool

Envoy → Host:
    tool_call         — forward a dynamic tool call to the host
    pong              — response to ping
    local_tools       — list of container-local tools
    local_tool_result — result of a container-local tool call
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Host → Envoy messages ──

@dataclass
class RegisterTools:
    """Push tool definitions to the Envoy."""
    tools: list[dict[str, Any]]
    type: str = "register_tools"


@dataclass
class ToolResult:
    """Response to a tool_call from the Envoy."""
    id: str
    result: dict[str, Any]
    type: str = "tool_result"


@dataclass
class SetCredential:
    """Provision a credential in the Envoy's in-memory store."""
    name: str
    value: str
    type: str = "set_credential"


@dataclass
class Ping:
    type: str = "ping"


@dataclass
class RequestLocalTools:
    """Ask the Envoy what container-local tools are available."""
    type: str = "request_local_tools"


@dataclass
class CallLocalTool:
    """Invoke a container-local tool (reverse direction)."""
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    type: str = "call_local_tool"


# ── Envoy → Host messages ──

@dataclass
class ToolCall:
    """Forward a dynamic tool call to the host."""
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    type: str = "tool_call"


@dataclass
class Pong:
    type: str = "pong"


@dataclass
class LocalTools:
    """List of container-local tools."""
    tools: list[dict[str, Any]]
    type: str = "local_tools"


@dataclass
class LocalToolResult:
    """Result of a container-local tool call."""
    id: str
    result: dict[str, Any]
    type: str = "local_tool_result"


# ── Serialization ──

def serialize(msg: Any) -> str:
    """Serialize a protocol message to a newline-terminated JSON string."""
    from dataclasses import asdict
    return json.dumps(asdict(msg)) + "\n"


def deserialize(line: str) -> dict[str, Any]:
    """Deserialize a newline-terminated JSON string."""
    return json.loads(line.strip())


import json  # noqa: E402 — used by serialize/deserialize
