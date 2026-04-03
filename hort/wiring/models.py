"""Pydantic models for the wiring system.

All models use ``extra="allow"`` and a ``version`` field for
forward/backward compatibility.  ``WireRuleset`` is the single
unified model used on every connection type — llming wires,
hort wires, direct wires, and fence boundaries.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Credential reference ──────────────────────────────────────────


# ── Tainted message ────────────────────────────────────────────────


class TaintedMessage(BaseModel):
    """A conversation message with per-message taint labels.

    When a tool call returns data, the resulting message carries the
    taint of that tool.  Later, when the LLM tries to use a tool that
    blocks that taint, the message is **redacted** — the LLM sees
    ``[Hidden: confidential content]`` instead of the actual text.

    The user always sees everything.  Only the LLM's view is filtered.
    """

    model_config = {"extra": "allow"}

    role: str                                # "user", "assistant", "system"
    content: str
    taint_labels: frozenset[str] = frozenset()
    tool_name: str = ""                      # tool that produced this message (if any)
    redacted_placeholder: str = "[Hidden: confidential content]"

    def redact_for(self, blocked_taint: set[str]) -> "TaintedMessage":
        """Return a copy with content replaced if taint overlaps."""
        if not blocked_taint or not self.taint_labels:
            return self
        if self.taint_labels & blocked_taint:
            return self.model_copy(update={
                "content": self.redacted_placeholder,
            })
        return self


class ConversationTaint(BaseModel):
    """Per-conversation taint state with message-level tracking.

    Each message knows its own taint.  The zone-level taint is the
    union of all messages' taint (for backward compatibility with
    zone-level checks).  But per-message redaction is the primary
    mechanism for mixed conversations.
    """

    model_config = {"extra": "allow"}

    messages: list[TaintedMessage] = Field(default_factory=list)
    zone: str = "public"

    @property
    def zone_taint(self) -> set[str]:
        """Union of all message taints in this conversation."""
        labels: set[str] = set()
        for msg in self.messages:
            labels |= msg.taint_labels
        return labels

    def add_message(
        self,
        role: str,
        content: str,
        taint_labels: frozenset[str] | None = None,
        tool_name: str = "",
    ) -> TaintedMessage:
        """Add a message with its taint labels."""
        msg = TaintedMessage(
            role=role,
            content=content,
            taint_labels=taint_labels or frozenset(),
            tool_name=tool_name,
        )
        self.messages.append(msg)
        return msg

    def visible_history(self, blocked_taint: set[str] | None = None) -> list[TaintedMessage]:
        """Return messages with tainted ones redacted.

        Messages whose taint overlaps ``blocked_taint`` have their
        content replaced with a placeholder.  The user sees the
        full history; the LLM sees the filtered version.
        """
        if not blocked_taint:
            return list(self.messages)
        return [msg.redact_for(blocked_taint) for msg in self.messages]

    def taint_since(self, tool_name: str) -> set[str]:
        """Get taint labels introduced since a specific tool was used."""
        labels: set[str] = set()
        found = False
        for msg in self.messages:
            if msg.tool_name == tool_name:
                found = True
            if found:
                labels |= msg.taint_labels
        return labels


# ── Credential reference ──────────────────────────────────────────


class CredentialRef(BaseModel):
    """A reference to a credential value.

    Supports three resolution schemes:
    - ``env:VAR_NAME`` — read from host environment variable
    - ``vault:path/to/secret`` — resolve from credential vault
    - ``file:/path/to/secret`` — read from file (first line, stripped)
    - Plain string — used as-is (NOT recommended for secrets)
    """

    value: str

    def is_env(self) -> bool:
        return self.value.startswith("env:")

    def is_vault(self) -> bool:
        return self.value.startswith("vault:")

    def is_file(self) -> bool:
        return self.value.startswith("file:")

    @property
    def key(self) -> str:
        """The part after the prefix."""
        if ":" in self.value:
            return self.value.split(":", 1)[1]
        return self.value


# ── Unified wire ruleset ──────────────────────────────────────────


class WireRuleset(BaseModel):
    """Unified rules for any connection type.

    Used identically on llming-to-hort wires, hort-to-hort wires,
    direct llming-to-llming wires, fence inside rules, and fence
    boundary rules.  One model, five contexts.
    """

    model_config = {"extra": "allow"}
    version: int = 1

    # Tool-level permissions (glob patterns)
    allow: list[str] | None = None
    deny: list[str] | None = None

    # Group-level permissions
    allow_groups: list[str] | None = None
    deny_groups: list[str] | None = None

    # Taint labels
    taint: str | list[str] | None = None
    block_taint: list[str] | None = None

    # Boundary filters (content inspection rules)
    filters: list[dict[str, Any]] | None = None

    # Metadata
    name: str = ""
    color: str = ""

    def taint_labels(self) -> list[str]:
        """Normalize taint to a list."""
        if self.taint is None:
            return []
        if isinstance(self.taint, str):
            return [self.taint]
        return list(self.taint)


# ── Tool groups ───────────────────────────────────────────────────


class ToolGroup(BaseModel):
    """A named collection of tool patterns.

    Groups can be auto-detected from tool name verbs, declared by
    llming authors, or defined by users.  Groups compose via
    ``include_groups``.
    """

    model_config = {"extra": "allow"}

    description: str = ""
    color: str = ""
    auto: list[str] | None = None
    tools: list[str] | None = None
    include_groups: list[str] | None = None
    add: list[str] | None = None
    remove: list[str] | None = None


# ── Fence ─────────────────────────────────────────────────────────


class FenceConfig(BaseModel):
    """A virtual boundary around a set of llmings.

    No container, no network isolation — purely rule enforcement.
    Components stay in their parent hort and can belong to multiple
    fences (overlapping).
    """

    model_config = {"extra": "allow"}

    name: str
    members: list[str]
    inside: WireRuleset = Field(default_factory=WireRuleset)
    boundary: WireRuleset = Field(default_factory=WireRuleset)


# ── Llming connection ─────────────────────────────────────────────


class LlmingConnection(BaseModel):
    """A llming wired into a hort, with optional rules and config.

    The ``to`` field is the llming identifier (``author/name``) or
    a sub-hort reference (``hort/name``).
    """

    model_config = {"extra": "allow"}

    to: str
    rules: WireRuleset = Field(default_factory=WireRuleset)

    # Llming-specific config (token, paths, port, etc.)
    config: dict[str, Any] = Field(default_factory=dict)

    # Credential references resolved at startup
    credentials: dict[str, str] = Field(default_factory=dict)


class DirectConnection(BaseModel):
    """A direct llming-to-llming wire, bypassing the agent."""

    model_config = {"extra": "allow"}

    between: list[str]
    rules: WireRuleset = Field(default_factory=WireRuleset)


# ── Container config ──────────────────────────────────────────────


class ContainerConfig(BaseModel):
    """Container specification for a hort."""

    model_config = {"extra": "allow"}

    memory: str = "2g"
    cpus: float = 2
    network: list[str] = Field(default_factory=list)
    image: str = ""


# ── Hort definition ──────────────────────────────────────────────


class AgentDef(BaseModel):
    """Agent configuration within a hort."""

    model_config = {"extra": "allow"}

    provider: str = "claude-code"
    model: str | None = None


class HortDef(BaseModel):
    """A hort definition — the universal isolation boundary.

    Can be the root hort, a sub-hort (Docker container), or a
    remote hort (another machine).
    """

    model_config = {"extra": "allow"}

    name: str = ""
    agent: AgentDef | None = None
    container: ContainerConfig | None = None
    credentials: dict[str, str] = Field(default_factory=dict)

    # Remote hort connection
    remote: dict[str, Any] | None = None
    trust: Literal["trusted", "sandboxed", "untrusted"] | None = None
    budget: dict[str, Any] | None = None

    # Llmings and wiring
    llmings: list[dict[str, Any]] = Field(default_factory=list)
    direct: list[DirectConnection] = Field(default_factory=list)
    fences: list[FenceConfig] = Field(default_factory=list)

    # Circuit triggers
    circuits: list[dict[str, Any]] = Field(default_factory=list)


# ── World config ──────────────────────────────────────────────────


class WorldConfig(BaseModel):
    """The entire world in a single config.

    Parsed from ``openhort.yaml``.  Contains the root hort,
    all sub-horts, and global group definitions.
    """

    model_config = {"extra": "allow"}

    groups: dict[str, ToolGroup] = Field(default_factory=dict)
    hort: HortDef = Field(default_factory=HortDef)
    sub_horts: dict[str, HortDef] = Field(default_factory=dict)
