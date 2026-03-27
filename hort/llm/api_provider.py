"""Base for API/SDK-based LLM providers.

API providers call an LLM via HTTP (Anthropic, OpenAI, Mistral, …).
Conversation history is managed by :class:`ConversationStore` — the
provider doesn't need to track state.

Subclasses implement :meth:`call_api` and :meth:`stream_api`.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Iterator, Literal

from .base import LLMChunk, LLMMessage, LLMProvider, LLMResponse
from .history import ConversationStore


class APIProvider(LLMProvider):
    """LLM accessed via HTTP API with managed conversation history."""

    provider_type: Literal["api"] = "api"

    def __init__(
        self,
        *,
        model: str = "",
        store: ConversationStore | None = None,
        timeout_minutes: int = 60,
    ) -> None:
        self.model = model
        self.store = store or ConversationStore()
        self.timeout_minutes = timeout_minutes

    @abstractmethod
    def call_api(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send messages to the API and return the full response."""
        ...  # pragma: no cover

    @abstractmethod
    def stream_api(
        self, messages: list[LLMMessage],
    ) -> Iterator[LLMChunk]:
        """Stream a response from the API."""
        ...  # pragma: no cover

    def send(
        self, message: str, *, conversation_id: str | None = None,
    ) -> LLMResponse:
        conv_id = conversation_id or self.store.create(
            self.name, self.model, timeout_minutes=self.timeout_minutes,
        )

        self.store.add_message(conv_id, "user", message)
        messages = self.store.get_messages(conv_id)

        response = self.call_api(messages)
        self.store.add_message(conv_id, "assistant", response.text)

        response.conversation_id = conv_id
        return response

    def stream(
        self, message: str, *, conversation_id: str | None = None,
    ) -> Iterator[LLMChunk]:
        conv_id = conversation_id or self.store.create(
            self.name, self.model, timeout_minutes=self.timeout_minutes,
        )

        self.store.add_message(conv_id, "user", message)
        messages = self.store.get_messages(conv_id)

        text_parts: list[str] = []
        for chunk in self.stream_api(messages):
            if chunk.kind == "text" and isinstance(chunk.data, str):
                text_parts.append(chunk.data)
            yield chunk

        self.store.add_message(conv_id, "assistant", "".join(text_parts))
        yield LLMChunk(kind="meta", data={"conversation_id": conv_id})

    def cleanup(self, conversation_id: str) -> None:
        self.store.delete(conversation_id)
