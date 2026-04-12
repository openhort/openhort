"""llming-models executor — multi-provider LLM via llming-models SDK.

Extends LlmExecutor so it works like any other LLM llming. Supports
Anthropic, OpenAI, Mistral, Google, Together, and any OpenAI-compatible
endpoint. Provider selection is automatic based on available API keys.

Also exposes the legacy APIProvider interface for direct library use.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterator

from hort.llm.api_provider import APIProvider
from hort.llm.base import LLMChunk, LLMMessage, LLMResponse
from hort.llm.history import ConversationStore
from hort.llming import LlmExecutor, SendResult

logger = logging.getLogger(__name__)


class LlmingModelsExecutor(LlmExecutor):
    """Multi-provider LLM executor via llming-models SDK.

    Config (from hort-config.yaml):
        model: claude_sonnet  (or gpt-4o, mistral-large, etc.)
        api_key: (optional, falls back to env vars)
    """

    provider_name = "llming-models"

    _model: str = "claude_sonnet"
    _system_prompt: str = ""
    _api_key: str = ""

    def activate(self, config: dict[str, Any]) -> None:
        self._config = config
        self._model = config.get("model", "claude_sonnet")
        self._system_prompt = config.get("system_prompt", "")
        self._api_key = config.get("api_key", "")
        self.log.info("llming-models executor activated (model=%s)", self._model)

    async def _send(self, session_key: str, text: str, system_prompt: str) -> SendResult:
        """Send via llming-models SDK."""
        try:
            provider = LlmingProvider(
                model=self._model,
                system_prompt=system_prompt or self._system_prompt or None,
                api_key=self._api_key or None,
            )
            response = provider.send(text)
            return SendResult(
                text=response.text,
                cost=response.cost,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        except Exception:
            logger.exception("llming-models send error")
            return SendResult(text="Something went wrong. Try again.")

    def get_pulse(self) -> dict[str, Any]:
        base = super().get_pulse()
        base["model"] = self._model
        return base


# ── Legacy APIProvider interface (for direct library use) ──


class LlmingProvider(APIProvider):
    """Multi-provider LLM via the llming-models SDK.

    Supports Anthropic, OpenAI, Mistral, Google, Together, and any
    OpenAI-compatible endpoint.
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
        """Create a fresh llming_models ChatSession."""
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

        if history:
            for msg in history[:-1]:
                role = Role.USER if msg.role == "user" else Role.ASSISTANT
                session.add_message(role, msg.content)  # type: ignore[union-attr]

        return session

    def call_api(self, messages: list[LLMMessage]) -> LLMResponse:
        chunks = list(self.stream_api(messages))
        text = "".join(
            c.data for c in chunks
            if c.kind == "text" and isinstance(c.data, str)
        )
        return LLMResponse(text=text)

    def stream_api(self, messages: list[LLMMessage]) -> Iterator[LLMChunk]:
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
