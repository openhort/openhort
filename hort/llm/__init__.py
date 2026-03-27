"""LLM provider framework — interfaces and conversation management.

Two provider families:

**CLI providers** — executable LLMs (Claude Code, Codex, aider, …).
Run as subprocesses in a temp dir or sandbox container.  They own
their conversation state; we just manage the process lifecycle.

**API providers** — SDK-bound LLMs (Anthropic, OpenAI, Mistral, …).
Called via HTTP.  We own the conversation history, store it in
:class:`ConversationStore`, and handle replay on resume.

Quick start::

    from hort.llm import ConversationStore
    from hort.llm.base import CLIProvider, APIProvider
"""

from .base import LLMChunk, LLMMessage, LLMProvider, LLMResponse, LLMUsage
from .history import ConversationMeta, ConversationStore

__all__ = [
    "ConversationMeta",
    "ConversationStore",
    "LLMChunk",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
]
