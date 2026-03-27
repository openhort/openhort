"""LLM provider interfaces and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Literal

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """A single message in a conversation."""

    role: Literal["user", "assistant", "system"]
    content: str


class LLMChunk(BaseModel):
    """One piece of a streamed LLM response."""

    kind: Literal["text", "thinking", "meta"]
    data: str | dict  # type: ignore[type-arg]


class LLMUsage(BaseModel):
    """Cumulative usage tracking across a session."""

    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    turn_count: int = 0
    budget_limit: float | None = None

    @property
    def budget_remaining(self) -> float | None:
        if self.budget_limit is None:
            return None
        return max(0.0, self.budget_limit - self.total_cost)

    @property
    def budget_exceeded(self) -> bool:
        if self.budget_limit is None:
            return False
        return self.total_cost >= self.budget_limit

    def record_turn(
        self,
        cost: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record usage for one turn (delta values)."""
        self.total_cost += cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.turn_count += 1

    def set_cumulative(
        self,
        total_cost: float,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
    ) -> None:
        """Set absolute cumulative values (for CLI providers that
        report cumulative totals rather than per-turn deltas)."""
        self.total_cost = total_cost
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens
        self.turn_count += 1

    def format_status(self) -> str:
        parts = [f"${self.total_cost:.4f}"]
        if self.budget_limit is not None:
            parts.append(f"/ ${self.budget_limit:.2f}")
        parts.append(f"({self.turn_count} turns)")
        tokens = self.total_input_tokens + self.total_output_tokens
        if tokens:
            parts.append(f"[{tokens:,} tokens]")
        return " ".join(parts)


class LLMResponse(BaseModel):
    """Complete result of an LLM call."""

    text: str
    conversation_id: str | None = None
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict = Field(default_factory=dict)  # type: ignore[type-arg]


class LLMProvider(ABC):
    """Base interface for all LLM providers.

    Subclass :class:`CLIProvider` for executable LLMs (Claude Code,
    Codex, aider) or :class:`APIProvider` for SDK-based LLMs
    (Anthropic API, OpenAI API, Mistral).
    """

    @property
    @abstractmethod
    def provider_type(self) -> Literal["cli", "api"]:
        """``'cli'`` for executable LLMs, ``'api'`` for SDK-based."""
        ...  # pragma: no cover

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. ``'claude-code'``)."""
        ...  # pragma: no cover

    @abstractmethod
    def send(
        self, message: str, *, conversation_id: str | None = None,
    ) -> LLMResponse:
        """Send a message and return the full response."""
        ...  # pragma: no cover

    @abstractmethod
    def stream(
        self, message: str, *, conversation_id: str | None = None,
    ) -> Iterator[LLMChunk]:
        """Stream a response as a sequence of chunks."""
        ...  # pragma: no cover

    def cleanup(self, conversation_id: str) -> None:
        """Release resources for a conversation (override if needed)."""
