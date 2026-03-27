"""MCP server configuration and management for sandbox sessions.

Handles dynamic assignment of MCP servers to Claude sessions with
tool filtering (allow/deny lists) and container-aware scope resolution.

Architecture:
    ┌──────────────────────────────────────────────────────────────┐
    │  Host                                                        │
    │                                                              │
    │  ┌─────────────┐  stdio   ┌──────────────┐                  │
    │  │ MCP Server A │◄───────►│ SSE Proxy    │ :PORT            │
    │  │ (outside)    │         │ + filtering   │                  │
    │  └─────────────┘         └──────┬───────┘                  │
    │                                  │ host.docker.internal      │
    │  ┌──────────────────────────────┼──────────────────────┐    │
    │  │  Docker Container            │                       │    │
    │  │                              ▼                       │    │
    │  │  claude -p --mcp-config ... --disallowedTools ...    │    │
    │  │              │                                       │    │
    │  │              ▼                                       │    │
    │  │  ┌──────────────┐                                    │    │
    │  │  │ MCP Server B │ (inside, direct stdio)             │    │
    │  │  └──────────────┘                                    │    │
    │  └──────────────────────────────────────────────────────┘    │
    └──────────────────────────────────────────────────────────────┘

Routing rules:
    needs_proxy = (container + outside/auto scope) OR has allow filter
    deny-only on non-proxied MCPs → --disallowedTools flag
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolFilter(BaseModel):
    """Control which tools from an MCP server are visible to Claude."""

    allow: list[str] | None = None
    deny: list[str] | None = None


class McpServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    scope: Literal["inside", "outside", "auto"] = "auto"
    tool_filter: ToolFilter | None = Field(None, alias="toolFilter")

    model_config = {"populate_by_name": True}


class McpConfig(BaseModel):
    """Top-level MCP configuration."""

    mcpServers: dict[str, McpServerConfig] = Field(default_factory=dict)


def load_mcp_config(path: str | Path) -> McpConfig:
    """Load MCP configuration from a JSON file."""
    data = json.loads(Path(path).read_text())
    return McpConfig.model_validate(data)


def parse_inline_mcp(spec: str) -> tuple[str, McpServerConfig]:
    """Parse an inline MCP spec: ``name=command arg1 arg2 ...``

    Returns ``(name, config)``.
    """
    if "=" not in spec:
        raise ValueError(
            f"Invalid MCP spec '{spec}'. Expected: name=command [args...]"
        )
    name, rest = spec.split("=", 1)
    parts = rest.split()
    if not parts:
        raise ValueError(f"MCP spec '{spec}' has no command")
    return name.strip(), McpServerConfig(command=parts[0], args=parts[1:])


def needs_proxy(server: McpServerConfig, container_mode: bool) -> bool:
    """Decide whether an MCP server needs an SSE proxy.

    True when:
    - Container mode and scope is outside/auto (can't run stdio across Docker)
    - Server has an allow-list filter (must intercept tools/list response)
    """
    if container_mode and server.scope in ("outside", "auto"):
        return True
    if server.tool_filter and server.tool_filter.allow is not None:
        return True
    return False


def resolve_servers(
    config: McpConfig,
    container_mode: bool,
) -> tuple[dict[str, McpServerConfig], dict[str, McpServerConfig]]:
    """Split servers into direct (stdio) and proxied groups.

    Returns ``(direct_servers, proxied_servers)``.
    """
    direct: dict[str, McpServerConfig] = {}
    proxied: dict[str, McpServerConfig] = {}

    for name, server in config.mcpServers.items():
        if needs_proxy(server, container_mode):
            proxied[name] = server
        else:
            direct[name] = server

    return direct, proxied


def build_claude_mcp_json(
    direct_servers: dict[str, McpServerConfig],
    proxy_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the JSON config for ``claude --mcp-config``.

    *direct_servers*: MCPs that run via stdio (command + args).
    *proxy_urls*: name → SSE URL mapping for proxied MCPs.
    """
    servers: dict[str, Any] = {}

    for name, cfg in direct_servers.items():
        entry: dict[str, Any] = {"command": cfg.command, "args": cfg.args}
        if cfg.env:
            entry["env"] = cfg.env
        servers[name] = entry

    if proxy_urls:
        for name, url in proxy_urls.items():
            servers[name] = {"url": url}

    return {"mcpServers": servers}


def compute_disallowed_tools(
    direct_servers: dict[str, McpServerConfig],
) -> list[str]:
    """Compute ``--disallowedTools`` patterns for non-proxied servers.

    Only deny-list filters produce entries here (allow-list servers
    are always proxied, so filtering happens at the proxy level).
    """
    patterns: list[str] = []
    for name, server in direct_servers.items():
        tf = server.tool_filter
        if tf and tf.deny:
            for tool in tf.deny:
                patterns.append(f"mcp__{name}__{tool}")
    return patterns


# ── Tool filtering (used by the SSE proxy) ────────────────────────────


def filter_tools_list(
    tools: list[dict[str, Any]], tf: ToolFilter
) -> list[dict[str, Any]]:
    """Filter a ``tools/list`` result based on a ToolFilter."""
    result = tools
    if tf.allow is not None:
        result = [t for t in result if t.get("name") in tf.allow]
    if tf.deny is not None:
        result = [t for t in result if t.get("name") not in tf.deny]
    return result


def is_tool_allowed(tool_name: str, tf: ToolFilter) -> bool:
    """Check whether a specific tool call is permitted."""
    if tf.allow is not None and tool_name not in tf.allow:
        return False
    if tf.deny is not None and tool_name in tf.deny:
        return False
    return True
