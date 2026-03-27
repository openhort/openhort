"""Integration tests: full signal flow from watcher to reaction."""

from __future__ import annotations

import asyncio

import pytest

from hort.signals.bus import SignalBus
from hort.signals.engine import LogReactionHandler, TriggerEngine
from hort.signals.models import (
    Processor,
    Reaction,
    Signal,
    Trigger,
    TriggerCondition,
)
from hort.signals.processors import reset_processor_state
from hort.signals.watchers import TimerWatcher


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_processor_state()


@pytest.mark.asyncio
async def test_timer_to_trigger_to_reaction() -> None:
    """Timer fires -> signal -> engine matches -> reaction fires."""
    bus = SignalBus()
    engine = TriggerEngine(bus)
    handler = LogReactionHandler()
    engine.set_reaction_handler(handler)

    engine.register_trigger(Trigger(
        trigger_id="timer-react",
        signal_pattern="timer.fired",
        reaction=Reaction(
            reaction_type="tool_call",
            config={"tool": "test:notify", "arguments": {"text": "Timer {timer_id}!"}},
        ),
    ))
    engine.start()

    watcher = TimerWatcher({
        "schedules": [
            {"timer_id": "quick", "signal_type": "timer.fired", "interval_seconds": 0.05},
        ],
    })
    await watcher.start(bus, "test-hort")
    await asyncio.sleep(0.15)
    await watcher.stop()
    engine.stop()

    assert len(handler.fired) >= 1
    reaction, signal = handler.fired[0]
    assert reaction.reaction_type == "tool_call"
    assert signal.signal_type == "timer.fired"
    assert signal.data["timer_id"] == "quick"


@pytest.mark.asyncio
async def test_pipeline_filter_blocks_reaction() -> None:
    """Signal arrives, pipeline filter drops it, no reaction fires."""
    bus = SignalBus()
    engine = TriggerEngine(bus)
    handler = LogReactionHandler()
    engine.set_reaction_handler(handler)

    engine.register_trigger(Trigger(
        trigger_id="filtered",
        signal_pattern="motion.detected",
        pipeline=[
            Processor(processor_type="filter", config={"field": "confidence", "operator": "gte", "value": 0.8}),
        ],
        reaction=Reaction(reaction_type="tool_call", config={"tool": "alert"}),
    ))
    engine.start()

    # Low confidence -> filtered out
    await bus.emit(Signal(
        signal_type="motion.detected", source="sensor/1", hort_id="h1",
        data={"confidence": 0.3, "zone": "hallway"},
    ))

    # High confidence -> passes
    await bus.emit(Signal(
        signal_type="motion.detected", source="sensor/1", hort_id="h1",
        data={"confidence": 0.95, "zone": "hallway"},
    ))

    engine.stop()

    assert len(handler.fired) == 1
    _, sig = handler.fired[0]
    assert sig.data["confidence"] == 0.95


@pytest.mark.asyncio
async def test_pipeline_transform_then_react() -> None:
    """Signal -> template processor adds field -> reaction sees it."""
    bus = SignalBus()
    engine = TriggerEngine(bus)
    handler = LogReactionHandler()
    engine.set_reaction_handler(handler)

    engine.register_trigger(Trigger(
        trigger_id="transform-react",
        signal_pattern="temp.*",
        pipeline=[
            Processor(processor_type="template", config={
                "template": "Temperature is {value}C in {room}",
                "output_field": "message",
            }),
        ],
        reaction=Reaction(reaction_type="message", config={"to": "user"}),
    ))
    engine.start()

    await bus.emit(Signal(
        signal_type="temp.changed", source="sensor/kitchen", hort_id="h1",
        data={"value": 22.5, "room": "kitchen"},
    ))

    engine.stop()

    assert len(handler.fired) == 1
    _, sig = handler.fired[0]
    assert sig.data["message"] == "Temperature is 22.5C in kitchen"


@pytest.mark.asyncio
async def test_multiple_triggers_same_signal() -> None:
    """One signal matches two triggers, both fire."""
    bus = SignalBus()
    engine = TriggerEngine(bus)
    handler = LogReactionHandler()
    engine.set_reaction_handler(handler)

    engine.register_trigger(Trigger(
        trigger_id="t1", signal_pattern="alert.*",
        reaction=Reaction(reaction_type="tool_call", config={"tool": "log"}),
    ))
    engine.register_trigger(Trigger(
        trigger_id="t2", signal_pattern="alert.*",
        reaction=Reaction(reaction_type="message", config={"to": "admin"}),
    ))
    engine.start()

    await bus.emit(Signal(signal_type="alert.fire", source="detector", hort_id="h1"))

    engine.stop()

    assert len(handler.fired) == 2
    types = {r.reaction_type for r, _ in handler.fired}
    assert types == {"tool_call", "message"}


@pytest.mark.asyncio
async def test_condition_and_pipeline_combined() -> None:
    """Trigger condition filters by zone, pipeline filters by confidence."""
    bus = SignalBus()
    engine = TriggerEngine(bus)
    handler = LogReactionHandler()
    engine.set_reaction_handler(handler)

    engine.register_trigger(Trigger(
        trigger_id="combined",
        signal_pattern="motion.*",
        conditions=[TriggerCondition(field="zone", operator="eq", value="garage")],
        pipeline=[
            Processor(processor_type="filter", config={"field": "confidence", "operator": "gte", "value": 0.9}),
        ],
        reaction=Reaction(reaction_type="tool_call", config={"tool": "alarm"}),
    ))
    engine.start()

    # Wrong zone
    await bus.emit(Signal(
        signal_type="motion.detected", source="s1", hort_id="h1",
        data={"zone": "kitchen", "confidence": 0.95},
    ))

    # Right zone, low confidence
    await bus.emit(Signal(
        signal_type="motion.detected", source="s1", hort_id="h1",
        data={"zone": "garage", "confidence": 0.5},
    ))

    # Right zone, high confidence -> fires
    await bus.emit(Signal(
        signal_type="motion.detected", source="s1", hort_id="h1",
        data={"zone": "garage", "confidence": 0.95},
    ))

    engine.stop()

    assert len(handler.fired) == 1
    _, sig = handler.fired[0]
    assert sig.data["zone"] == "garage"
    assert sig.data["confidence"] == 0.95
