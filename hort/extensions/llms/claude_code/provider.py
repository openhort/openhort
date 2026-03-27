"""Claude Code CLI provider — wraps ``claude -p`` as an LLM provider."""

from __future__ import annotations

import subprocess
from typing import Iterator

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
        max_budget: float | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.model = model
        self.system_prompt = system_prompt
        self.container = container
        self.mcp_config_path = mcp_config_path
        self.disallowed_tools = disallowed_tools
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
            "--dangerously-skip-permissions",
        ]
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
