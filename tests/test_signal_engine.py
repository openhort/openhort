"""Tests for the trigger engine."""

from __future__ import annotations

import time

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


def _sig(signal_type: str = "test", source: str = "unit", **data: object) -> Signal:
    return Signal(signal_type=signal_type, source=source, hort_id="h1", data=data)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_processor_state()


@pytest.fixture
def setup():
    bus = SignalBus()
    engine = TriggerEngine(bus)
    handler = LogReactionHandler()
    engine.set_reaction_handler(handler)
    engine.start()
    return bus, engine, handler


@pytest.mark.asyncio
async def test_trigger_matches_and_fires(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="motion.*",
        reaction=Reaction(reaction_type="tool_call", config={"tool": "notify"}),
    ))
    await bus.emit(_sig("motion.detected"))
    assert len(handler.fired) == 1
    assert handler.fired[0][1].signal_type == "motion.detected"


@pytest.mark.asyncio
async def test_no_match_no_fire(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="washer.*",
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig("motion.detected"))
    assert len(handler.fired) == 0


@pytest.mark.asyncio
async def test_conditions_must_all_match(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="motion.*",
        conditions=[
            TriggerCondition(field="confidence", operator="gte", value=0.8),
            TriggerCondition(field="zone", operator="eq", value="hallway"),
        ],
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    # Both match
    await bus.emit(_sig("motion.detected", confidence=0.9, zone="hallway"))
    assert len(handler.fired) == 1
    # One fails
    await bus.emit(_sig("motion.detected", confidence=0.9, zone="kitchen"))
    assert len(handler.fired) == 1  # still 1


@pytest.mark.asyncio
async def test_condition_fails_no_fire(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        conditions=[TriggerCondition(field="value", operator="gt", value=100)],
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig(value=50))
    assert len(handler.fired) == 0


@pytest.mark.asyncio
async def test_source_filter(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        source_filter="pi-kitchen/*",
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig(source="pi-kitchen/sensor1"))
    await bus.emit(_sig(source="pi-garage/sensor1"))
    assert len(handler.fired) == 1


@pytest.mark.asyncio
async def test_cooldown_suppresses(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        cooldown_seconds=100,
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig())
    await bus.emit(_sig())
    assert len(handler.fired) == 1  # second suppressed


@pytest.mark.asyncio
async def test_disabled_trigger_skipped(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        enabled=False,
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig())
    assert len(handler.fired) == 0


@pytest.mark.asyncio
async def test_pipeline_filter_drops(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        pipeline=[Processor(processor_type="filter", config={"field": "x", "operator": "eq", "value": 1})],
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig(x=2))  # filtered out
    await bus.emit(_sig(x=1))  # passes
    assert len(handler.fired) == 1


@pytest.mark.asyncio
async def test_pipeline_template_modifies(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        pipeline=[Processor(processor_type="template", config={"template": "Alert: {zone}", "output_field": "msg"})],
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig(zone="kitchen"))
    assert len(handler.fired) == 1
    _, sig = handler.fired[0]
    assert sig.data["msg"] == "Alert: kitchen"


@pytest.mark.asyncio
async def test_unregister_trigger(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    engine.unregister_trigger("t1")
    await bus.emit(_sig())
    assert len(handler.fired) == 0


@pytest.mark.asyncio
async def test_stop_unsubscribes(setup) -> None:
    bus, engine, handler = setup
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    engine.stop()
    await bus.emit(_sig())
    assert len(handler.fired) == 0


@pytest.mark.asyncio
async def test_reaction_error_does_not_crash(setup) -> None:
    bus, engine, _ = setup

    class BadHandler:
        async def handle(self, reaction, signal):
            raise RuntimeError("boom")

    engine.set_reaction_handler(BadHandler())
    engine.register_trigger(Trigger(
        trigger_id="t1",
        signal_pattern="*",
        reaction=Reaction(reaction_type="tool_call", config={}),
    ))
    await bus.emit(_sig())  # should not raise


def test_trigger_count(setup) -> None:
    _, engine, _ = setup
    assert engine.trigger_count == 0
    engine.register_trigger(Trigger(trigger_id="a", signal_pattern="*"))
    engine.register_trigger(Trigger(trigger_id="b", signal_pattern="*"))
    assert engine.trigger_count == 2
