"""Pydantic models for the Signal system.

All models use ``extra = "allow"`` and a ``version`` field for
forward/backward compatibility across releases.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """A typed, timestamped event in the Hort ecosystem."""

    model_config = {"extra": "allow"}

    version: int = 1
    signal_type: str
    source: str
    hort_id: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    data: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: float | None = None
    correlation_id: str | None = None


class TriggerCondition(BaseModel):
    """A condition that must be true for a trigger to fire."""

    model_config = {"extra": "allow"}

    field: str
    operator: str  # eq, ne, gt, lt, gte, lte, in, contains, matches
    value: Any


class Processor(BaseModel):
    """A processing step in a signal pipeline."""

    model_config = {"extra": "allow"}

    version: int = 1
    processor_type: str
    config: dict[str, Any] = Field(default_factory=dict)


class Reaction(BaseModel):
    """What to do when a trigger fires."""

    model_config = {"extra": "allow"}

    version: int = 1
    reaction_type: str  # tool_call, message, llm_prompt, signal
    config: dict[str, Any] = Field(default_factory=dict)


class Trigger(BaseModel):
    """A rule that activates when matching signals arrive."""

    model_config = {"extra": "allow"}

    version: int = 1
    trigger_id: str
    signal_pattern: str
    conditions: list[TriggerCondition] = Field(default_factory=list)
    cooldown_seconds: float = 0
    source_filter: str | None = None
    enabled: bool = True
    pipeline: list[Processor] = Field(default_factory=list)
    reaction: Reaction | None = None


class WatcherConfig(BaseModel):
    """Configuration for an event source watcher."""

    model_config = {"extra": "allow"}

    version: int = 1
    watcher_type: str  # timer, polling, mqtt, homeassistant, webhook
    config: dict[str, Any] = Field(default_factory=dict)
    signal_mapping: dict[str, str] = Field(default_factory=dict)
