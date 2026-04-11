"""llming-models provider — wraps llming_models.ChatSession as an APIProvider.

Supports two execution modes:

Local mode:
    Provider runs in the current process. API key from env or constructor.
    Conversation history in ConversationStore (JSON files).

Container mode:
    Provider runs inside a Docker sandbox. API key injected via
    ephemeral env var (not written to disk). MCP servers supported
    via the same proxy system as Claude Code.
"""

from __future__ import annotations

import asyncio
from typing import Iterator

from hort.llm.api_provider import APIProvider
from hort.llm.base import LLMChunk, LLMMessage, LLMResponse
from hort.llm.history import ConversationStore


class LlmingProvider(APIProvider):
    """Multi-provider LLM via the llming-models SDK.

    Supports Anthropic, OpenAI, Mistral, Google, Together, and any
    OpenAI-compatible endpoint. Provider selection is automatic
    based on available API keys.
    """

    name = "llming"

    def __init__(
        self,
        *,
        model: str = "claude_sonnet",
        system_prompt: str | None = None,
        store: ConversationStore | None = None,
        timeout_minutes: int = 60,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            model=model, store=store, timeout_minutes=timeout_minutes,
        )
        self.system_prompt = system_prompt
        self.api_key = api_key
        self._session: object | None = None

    def _make_session(self, history: list[LLMMessage] | None = None) -> object:
        """Create a fresh llming_models ChatSession, optionally pre-loaded
        with conversation history for resume."""
        import os

        from llming_models import LLMManager
        from llming_models.llm_base_models import Role

        if self.api_key:
            os.environ.setdefault("ANTHROPIC_API_KEY", self.api_key)

        manager = LLMManager()
        session = manager.create_session(
            model=self.model,
            system_prompt=self.system_prompt or "",
        )

        # Replay stored history so the session has full context
        if history:
            for msg in history[:-1]:  # all except the last (we'll send that)
                role = Role.USER if msg.role == "user" else Role.ASSISTANT
                session.add_message(role, msg.content)  # type: ignore[union-attr]

        return session

    def call_api(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send messages via streaming internally (Anthropic SDK requires it)."""
        chunks = list(self.stream_api(messages))
        text = "".join(
            c.data for c in chunks
            if c.kind == "text" and isinstance(c.data, str)
        )
        return LLMResponse(text=text)

    def stream_api(self, messages: list[LLMMessage]) -> Iterator[LLMChunk]:
        """Stream a response. Creates a new session with replayed history."""
        session = self._make_session(messages)
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )

        loop = asyncio.new_event_loop()
        try:
            stream = loop.run_until_complete(
                session.chat_async(last_user, streaming=True),  # type: ignore[union-attr]
            )

            async def _drain() -> list[LLMChunk]:
                chunks: list[LLMChunk] = []
                async for chunk in stream:
                    if chunk.content:
                        chunks.append(LLMChunk(kind="text", data=chunk.content))
                return chunks

            chunks = loop.run_until_complete(_drain())
        finally:
            loop.close()

        yield from chunks
