"""Base for CLI-executed LLM providers.

CLI providers run an LLM as a subprocess — either locally in a temp
directory or inside a sandbox container.  The LLM tool manages its
own conversation state; we just handle process lifecycle and output
parsing.

Subclasses implement :meth:`build_command` and :meth:`parse_stream`.
"""

from __future__ import annotations

import subprocess
from abc import abstractmethod
from typing import TYPE_CHECKING, Iterator, Literal

from .base import LLMChunk, LLMProvider, LLMResponse

if TYPE_CHECKING:
    from hort.sandbox import Session


class CLIProvider(LLMProvider):
    """LLM that runs as a subprocess."""

    provider_type: Literal["cli"] = "cli"

    def __init__(
        self,
        *,
        session: Session | None = None,
        cwd: str | None = None,
    ) -> None:
        self.session = session
        self.cwd = cwd

    @abstractmethod
    def build_command(
        self, message: str, conversation_id: str | None,
    ) -> list[str]:
        """Return the full command list (e.g. ``['claude', '-p', ...]``)."""
        ...  # pragma: no cover

    @abstractmethod
    def parse_stream(
        self, proc: subprocess.Popen[bytes],
    ) -> Iterator[LLMChunk]:
        """Parse the subprocess stdout into LLM chunks."""
        ...  # pragma: no cover

    def send(
        self, message: str, *, conversation_id: str | None = None,
    ) -> LLMResponse:
        text_parts: list[str] = []
        meta: dict = {}
        for chunk in self.stream(message, conversation_id=conversation_id):
            if chunk.kind == "text" and isinstance(chunk.data, str):
                text_parts.append(chunk.data)
            elif chunk.kind == "meta" and isinstance(chunk.data, dict):
                meta = chunk.data

        return LLMResponse(
            text="".join(text_parts),
            conversation_id=meta.get("session_id")
            or meta.get("conversation_id"),
            cost=meta.get("cost", 0),
        )

    def stream(
        self, message: str, *, conversation_id: str | None = None,
    ) -> Iterator[LLMChunk]:
        cmd = self.build_command(message, conversation_id)

        if self.session:
            proc = self.session.exec_streaming(cmd)
        else:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                cwd=self.cwd,
            )

        yield from self.parse_stream(proc)
