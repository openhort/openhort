"""Unified conversation history store for API-based LLMs.

Stores conversations as JSON files in ``~/.openhort/conversations/``.
Each conversation tracks its messages, provider, model, and a
timeout for automatic cleanup.  The reaper calls
:meth:`ConversationStore.cleanup_expired` to garbage-collect stale
conversations alongside sandbox sessions.

Storage format::

    ~/.openhort/conversations/
      abc123def456.json   ← one file per conversation
      789012345678.json
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .base import LLMMessage

DEFAULT_HISTORY_DIR = Path.home() / ".openhort" / "conversations"


class ConversationMeta(BaseModel):
    """Persisted conversation metadata + messages."""

    id: str
    provider: str
    model: str
    created_at: str
    last_active: str
    timeout_minutes: int = 60
    messages: list[LLMMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationStore:
    """CRUD + cleanup for conversation history."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self.store_dir = store_dir or DEFAULT_HISTORY_DIR
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        provider: str,
        model: str,
        timeout_minutes: int = 60,
    ) -> str:
        """Create a new conversation.  Returns the conversation ID."""
        conv_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        meta = ConversationMeta(
            id=conv_id,
            provider=provider,
            model=model,
            created_at=now,
            last_active=now,
            timeout_minutes=timeout_minutes,
        )
        self._save(meta)
        return conv_id

    def add_message(self, conv_id: str, role: str, content: str) -> None:
        """Append a message to a conversation."""
        meta = self._load(conv_id)
        if meta is None:
            raise ValueError(f"Conversation {conv_id} not found")
        meta.messages.append(LLMMessage(role=role, content=content))  # type: ignore[arg-type]
        meta.last_active = datetime.now(timezone.utc).isoformat()
        self._save(meta)

    def get_messages(self, conv_id: str) -> list[LLMMessage]:
        """Return all messages for a conversation."""
        meta = self._load(conv_id)
        return meta.messages if meta else []

    def get(self, conv_id: str) -> ConversationMeta | None:
        """Load full conversation metadata."""
        return self._load(conv_id)

    def delete(self, conv_id: str) -> bool:
        """Delete a conversation.  Returns True if it existed."""
        path = self.store_dir / f"{conv_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def list_conversations(self) -> list[ConversationMeta]:
        """Return all conversations, newest first."""
        convos: list[ConversationMeta] = []
        for path in self.store_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                convos.append(ConversationMeta.model_validate(data))
            except (json.JSONDecodeError, Exception):
                continue
        convos.sort(key=lambda c: c.last_active, reverse=True)
        return convos

    def cleanup_expired(self) -> list[str]:
        """Remove conversations idle beyond their timeout.  Returns IDs."""
        destroyed: list[str] = []
        now = datetime.now(timezone.utc)
        for conv in self.list_conversations():
            last = datetime.fromisoformat(conv.last_active)
            if now - last > timedelta(minutes=conv.timeout_minutes):
                self.delete(conv.id)
                destroyed.append(conv.id)
        return destroyed

    def _save(self, meta: ConversationMeta) -> None:
        path = self.store_dir / f"{meta.id}.json"
        path.write_text(meta.model_dump_json(indent=2))

    def _load(self, conv_id: str) -> ConversationMeta | None:
        path = self.store_dir / f"{conv_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return ConversationMeta.model_validate(data)
        except (json.JSONDecodeError, Exception):
            return None
