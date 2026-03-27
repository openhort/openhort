"""Trigger engine — matches signals to triggers, runs pipelines, fires reactions."""

from __future__ import annotations

import logging
import time
from typing import Protocol

from hort.signals.bus import SignalBus, _matches
from hort.signals.models import Reaction, Signal, Trigger
from hort.signals.processors import evaluate_condition, run_pipeline

logger = logging.getLogger("hort.signals.engine")


class ReactionHandler(Protocol):
    """Protocol for handling fired reactions."""

    async def handle(self, reaction: Reaction, signal: Signal) -> None: ...


class LogReactionHandler:
    """Default handler that logs reactions (for testing/debugging)."""

    def __init__(self) -> None:
        self.fired: list[tuple[Reaction, Signal]] = []

    async def handle(self, reaction: Reaction, signal: Signal) -> None:
        self.fired.append((reaction, signal))
        logger.info(
            "Reaction fired: %s for %s", reaction.reaction_type, signal.signal_type,
        )


class TriggerEngine:
    """Evaluates triggers against incoming signals."""

    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus
        self._triggers: dict[str, Trigger] = {}
        self._cooldowns: dict[str, float] = {}
        self._sub_id: str | None = None
        self._handler: ReactionHandler | None = None

    def register_trigger(self, trigger: Trigger) -> None:
        """Register a trigger for evaluation."""
        self._triggers[trigger.trigger_id] = trigger

    def unregister_trigger(self, trigger_id: str) -> None:
        """Remove a trigger."""
        self._triggers.pop(trigger_id, None)

    def set_reaction_handler(self, handler: ReactionHandler) -> None:
        """Set the handler for fired reactions."""
        self._handler = handler

    def start(self) -> None:
        """Subscribe to the bus and begin evaluating triggers."""
        self._sub_id = self._bus.subscribe("*", self._on_signal)

    def stop(self) -> None:
        """Unsubscribe from the bus."""
        if self._sub_id:
            self._bus.unsubscribe(self._sub_id)
            self._sub_id = None

    @property
    def trigger_count(self) -> int:
        return len(self._triggers)

    async def _on_signal(self, signal: Signal) -> None:
        for trigger in list(self._triggers.values()):
            if not trigger.enabled:
                continue
            if not _matches(trigger.signal_pattern, signal.signal_type):
                continue
            if trigger.source_filter and not _matches(
                trigger.source_filter, signal.source,
            ):
                continue
            if not self._check_conditions(trigger, signal):
                continue
            if not self._check_cooldown(trigger):
                continue

            # Run pipeline
            processed: Signal | None = signal
            if trigger.pipeline:
                processed = await run_pipeline(signal, trigger.pipeline)
                if processed is None:
                    continue

            # Fire reaction
            self._cooldowns[trigger.trigger_id] = time.monotonic()
            if trigger.reaction and self._handler:
                try:
                    await self._handler.handle(trigger.reaction, processed)
                except Exception:
                    logger.exception(
                        "Reaction error for trigger %s", trigger.trigger_id,
                    )

    @staticmethod
    def _check_conditions(trigger: Trigger, signal: Signal) -> bool:
        for cond in trigger.conditions:
            value = signal.data.get(cond.field)
            if not evaluate_condition(value, cond.operator, cond.value):
                return False
        return True

    def _check_cooldown(self, trigger: Trigger) -> bool:
        if trigger.cooldown_seconds <= 0:
            return True
        last = self._cooldowns.get(trigger.trigger_id, 0.0)
        return (time.monotonic() - last) >= trigger.cooldown_seconds
