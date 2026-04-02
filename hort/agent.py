"""Reusable AI agent configuration and session management.

The ``agent`` section in ``hort-config.yaml`` defines a single shared
agent configuration that any connector (Telegram, Discord, web chat)
or trigger can reference.  This avoids duplicating provider/model/
container settings across every consumer.

Example config::

    agent:
      provider: claude-code
      model: claude-sonnet-4-6
      container: true
      dangerous_mode: false
      memory: 2g
      cpus: 2
      allowed_tools:
        - Bash
        - Read
        - Write
        - Edit
        - Glob
        - Grep
        - "mcp__openhort__*"

Consumers read the agent config via ``get_agent_config()`` and create
container-backed chat sessions via ``AgentSession``.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("hort.agent")

# Default tools allowed when dangerous_mode is off.
# Covers file operations, shell, and all openhort MCP tools.
DEFAULT_ALLOWED_TOOLS: list[str] = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "mcp__openhort__*",
]

# Image that has the Claude Code CLI pre-installed
CLAUDE_CODE_IMAGE = "openhort-claude-code:latest"


class AgentConfig(BaseModel):
    """Shared AI agent configuration — single node in hort-config.yaml.

    Connectors and triggers read this instead of defining their own
    LLM settings.  Defaults are secure: container isolation enabled,
    dangerous mode disabled.
    """

    provider: str = "claude-code"
    model: str | None = None
    container: bool = True
    dangerous_mode: bool = False
    memory: str = "2g"
    cpus: float = 2
    image: str = CLAUDE_CODE_IMAGE
    allowed_tools: list[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    max_budget_usd: float | None = None
    system_prompt: str = ""
    progress_interval: float = 8.0


def get_agent_config() -> AgentConfig:
    """Load agent config from hort-config.yaml, with secure defaults."""
    from hort.config import get_store

    raw: dict[str, Any] = get_store().get("agent")
    if not raw:
        return AgentConfig()
    return AgentConfig.model_validate(raw)
