"""Pydantic models for Hort configuration.

A Hort config defines what lives inside a Hort (components),
what it exports/imports, and its sub-Horts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Components (things that live inside a Hort) ─────────────────────


class McpComponentDef(BaseModel):
    """An MCP server component."""
    model_config = {"extra": "allow"}
    component_id: str
    component_type: Literal["mcp"] = "mcp"
    label: str = ""
    command: str = ""                          # e.g. "npx @anthropic/mcp-filesystem /tmp"
    transport: Literal["stdio", "sse", "http"] = "stdio"
    url: str | None = None                     # for sse/http transport
    env: dict[str, str] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class LlmingComponentDef(BaseModel):
    """An LLMing (AI agent) component."""
    model_config = {"extra": "allow"}
    component_id: str
    component_type: Literal["llming"] = "llming"
    label: str = ""
    provider: str = "claude-code"              # claude-code, openai, anthropic, llming-model
    model: str = "sonnet"
    api_key_source: str = "keychain"
    system_prompt: str = ""
    budget_usd: float = 1.0
    max_turns: int = 50
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class WatcherComponentDef(BaseModel):
    """A screen watcher component."""
    model_config = {"extra": "allow"}
    component_id: str
    component_type: Literal["watcher"] = "watcher"
    label: str = ""
    app_filter: str = ""
    window_filter: str = ""
    region: str = "full"
    poll_interval: float = 1.0
    idle_threshold: float = 10.0
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class NotifierComponentDef(BaseModel):
    """A notification output component (Telegram, etc.)."""
    model_config = {"extra": "allow"}
    component_id: str
    component_type: Literal["notifier"] = "notifier"
    label: str = ""
    channel: Literal["telegram", "webhook", "log"] = "telegram"
    message_template: str = "{message}"
    on_event: Literal["change", "idle", "both", "any"] = "both"
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


# Union of all component types
ComponentDef = McpComponentDef | LlmingComponentDef | WatcherComponentDef | NotifierComponentDef


# ── Connections between components ──────────────────────────────────


class ConnectionDef(BaseModel):
    """A connection between two components within a Hort."""
    model_config = {"extra": "allow"}
    source_id: str     # component_id of source
    target_id: str     # component_id of target
    label: str = ""    # optional description


# ── Exports / Imports ───────────────────────────────────────────────


class ExportDef(BaseModel):
    """A tool exported from this Hort."""
    model_config = {"extra": "allow"}
    component_id: str                       # which component to export
    to: list[str] = Field(default_factory=lambda: ["*"])  # target hort IDs or "*"
    tools: list[str] = Field(default_factory=lambda: ["*"])  # which MCP tools
    read_only: bool = False


class ImportDef(BaseModel):
    """A tool imported from another Hort."""
    model_config = {"extra": "allow"}
    component_id: str                       # local alias
    from_hort: str                          # source hort ID
    remote_component: str                   # component_id on the remote Hort
    tools: list[str] = Field(default_factory=lambda: ["*"])


# ── Sub-Hort ────────────────────────────────────────────────────────


class SubHortDef(BaseModel):
    """A container sub-Hort nested inside this Hort."""
    model_config = {"extra": "allow"}
    hort_id: str
    label: str = ""
    memory: str | None = None
    cpus: float | None = None
    network: Literal["none", "restricted", "full"] = "restricted"
    components: list[ComponentDef] = Field(default_factory=list)
    connections: list[ConnectionDef] = Field(default_factory=list)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


# ── Root Hort config ────────────────────────────────────────────────


class HortConfig(BaseModel):
    """Complete configuration for a Hort (machine-level)."""
    model_config = {"extra": "allow"}

    hort_id: str
    name: str = "My Hort"
    description: str = ""
    node_id: str = ""                        # human-readable (e.g. "mac-studio")

    # What lives directly in this Hort
    components: list[ComponentDef] = Field(default_factory=list)
    connections: list[ConnectionDef] = Field(default_factory=list)

    # Sub-Horts (containers)
    sub_horts: list[SubHortDef] = Field(default_factory=list)

    # Cross-Hort tool sharing
    exports: list[ExportDef] = Field(default_factory=list)
    imports: list[ImportDef] = Field(default_factory=list)


# ── Block catalog for the UI ────────────────────────────────────────


class BlockFieldDef(BaseModel):
    name: str
    label: str
    field_type: str = "text"
    default: Any = ""
    options: list[str] | None = None
    description: str = ""


class BlockTypeDef(BaseModel):
    block_type: str
    label: str
    description: str = ""
    icon: str = "ph-puzzle-piece"
    category: str = "general"
    color: str = "#3b82f6"
    fields: list[BlockFieldDef] = Field(default_factory=list)
    inputs: int = 1
    outputs: int = 1


BLOCK_CATALOG: list[BlockTypeDef] = [
    BlockTypeDef(
        block_type="mcp", label="MCP Server", icon="ph-plug", category="tool", color="#f59e0b",
        description="External tool via Model Context Protocol",
        fields=[
            BlockFieldDef(name="command", label="Command", description="e.g. npx @anthropic/mcp-filesystem /tmp"),
            BlockFieldDef(name="transport", label="Transport", field_type="select", default="stdio", options=["stdio", "sse", "http"]),
            BlockFieldDef(name="url", label="URL", description="For SSE/HTTP transport"),
        ],
    ),
    BlockTypeDef(
        block_type="llming", label="LLMing", icon="ph-brain", category="agent", color="#8b5cf6",
        description="AI agent (Claude, GPT, local model)",
        fields=[
            BlockFieldDef(name="provider", label="Provider", field_type="select", default="claude-code", options=["claude-code", "openai", "anthropic", "llming-model"]),
            BlockFieldDef(name="model", label="Model", field_type="select", default="sonnet", options=["sonnet", "haiku", "opus"]),
            BlockFieldDef(name="api_key_source", label="API Key", field_type="select", default="keychain", options=["keychain", "env:ANTHROPIC_API_KEY", "env:OPENAI_API_KEY"]),
            BlockFieldDef(name="system_prompt", label="System Prompt", field_type="textarea"),
            BlockFieldDef(name="budget_usd", label="Budget ($)", field_type="number", default=1.0),
        ],
    ),
    BlockTypeDef(
        block_type="watcher", label="Screen Watcher", icon="ph-eye", category="input", color="#22c55e",
        inputs=0, outputs=1,
        description="Watch a window for visual changes",
        fields=[
            BlockFieldDef(name="app_filter", label="App Name", description="e.g. iTerm, Chrome"),
            BlockFieldDef(name="window_filter", label="Window Title", description="Glob pattern, e.g. *claude*"),
            BlockFieldDef(name="region", label="Region", field_type="select", default="full", options=["full", "left", "right", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right", "center"]),
            BlockFieldDef(name="poll_interval", label="Poll (sec)", field_type="number", default=1.0),
            BlockFieldDef(name="idle_threshold", label="Idle (sec)", field_type="number", default=10.0),
        ],
    ),
    BlockTypeDef(
        block_type="notifier", label="Telegram", icon="ph-telegram-logo", category="output", color="#2563eb",
        inputs=1, outputs=0,
        description="Send notification via Telegram",
        fields=[
            BlockFieldDef(name="message_template", label="Message", field_type="textarea", default="Screen changed: {window}", description="Use {field} for signal data"),
            BlockFieldDef(name="on_event", label="Trigger On", field_type="select", default="both", options=["change", "idle", "both", "any"]),
        ],
    ),
    BlockTypeDef(
        block_type="sub_hort", label="Sub-Hort", icon="ph-cube", category="hort", color="#ec4899",
        description="Container sandbox (isolated environment)",
        fields=[
            BlockFieldDef(name="memory", label="Memory", default="1g", description="e.g. 512m, 2g"),
            BlockFieldDef(name="cpus", label="CPUs", field_type="number", default=2),
            BlockFieldDef(name="network", label="Network", field_type="select", default="restricted", options=["none", "restricted", "full"]),
        ],
    ),
]
