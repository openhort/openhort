"""Claude Code CLI provider — wraps ``claude -p`` as an LLM provider.

Reads security settings from :class:`~hort.agent.AgentConfig`.  By
default ``--dangerously-skip-permissions`` is **not** used — instead
``--allowedTools`` pre-approves a whitelist of tools.  Only when
``AgentConfig.dangerous_mode`` is explicitly ``True`` is the dangerous
flag added.
"""

from __future__ import annotations

import subprocess
from typing import Iterator

from hort.agent import AgentConfig, DEFAULT_ALLOWED_TOOLS
from hort.llm.base import LLMChunk
from hort.llm.cli_provider import CLIProvider

from .stream import stream_response

# Appended so Claude outputs plain text, not markdown
_PLAIN_TEXT_INSTRUCTION = (
    "You are in a plain terminal chat. Do not use markdown formatting: "
    "no >, **, `, #, or other markdown syntax. Use plain text only."
)


class ClaudeCodeProvider(CLIProvider):
    """Runs Claude Code CLI as a subprocess."""

    name = "claude-code"

    def __init__(
        self,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        container: bool = False,
        mcp_config_path: str | None = None,
        disallowed_tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        dangerous_mode: bool = False,
        max_budget: float | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.model = model
        self.system_prompt = system_prompt
        self.container = container
        self.mcp_config_path = mcp_config_path
        self.disallowed_tools = disallowed_tools
        self.allowed_tools = allowed_tools or list(DEFAULT_ALLOWED_TOOLS)
        self.dangerous_mode = dangerous_mode
        self.max_budget = max_budget
        self._turn_count = 0

    def build_command(
        self, message: str, conversation_id: str | None,
    ) -> list[str]:
        args: list[str] = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if self.dangerous_mode:
            args.append("--dangerously-skip-permissions")
        elif self.allowed_tools:
            args.extend(["--allowedTools", ",".join(self.allowed_tools)])
        if self.container:
            args.append("--bare")
        if self.model:
            args.extend(["--model", self.model])
        if self.system_prompt and self._turn_count == 0:
            args.extend(["--system-prompt", self.system_prompt])
        if self._turn_count == 0:
            args.extend(["--append-system-prompt", _PLAIN_TEXT_INSTRUCTION])
        if conversation_id:
            args.extend(["--resume", conversation_id])
        if self.mcp_config_path:
            args.extend(["--mcp-config", self.mcp_config_path])
        if self.disallowed_tools:
            args.extend(["--disallowedTools", ",".join(self.disallowed_tools)])
        if self.max_budget is not None:
            args.extend(["--max-budget-usd", str(self.max_budget)])
        args.append(message)
        self._turn_count += 1
        return args

    def parse_stream(
        self, proc: subprocess.Popen[bytes],
    ) -> Iterator[LLMChunk]:
        for kind, data in stream_response(proc):
            if kind == "text":
                yield LLMChunk(kind="text", data=data)
            elif kind == "meta":
                yield LLMChunk(kind="meta", data=data)
