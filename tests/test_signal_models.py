"""Tests for Signal system Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone

from hort.signals.models import (
    Processor,
    Reaction,
    Signal,
    Trigger,
    TriggerCondition,
    WatcherConfig,
)


def test_signal_defaults() -> None:
    s = Signal(signal_type="test", source="unit", hort_id="h1")
    assert s.version == 1
    assert s.signal_type == "test"
    assert s.data == {}
    assert s.ttl_seconds is None
    assert isinstance(s.timestamp, datetime)


def test_signal_with_data() -> None:
    s = Signal(
        signal_type="motion.detected",
        source="sensor/1",
        hort_id="h1",
        data={"zone": "hallway", "confidence": 0.95},
    )
    assert s.data["zone"] == "hallway"
    assert s.data["confidence"] == 0.95


def test_signal_extra_fields_accepted() -> None:
    s = Signal(
        signal_type="test",
        source="unit",
        hort_id="h1",
        future_field="value",  # type: ignore[call-arg]
    )
    assert s.future_field == "value"  # type: ignore[attr-defined]


def test_signal_json_roundtrip() -> None:
    s = Signal(
        signal_type="test.roundtrip",
        source="unit",
        hort_id="h1",
        data={"key": "value"},
    )
    json_str = s.model_dump_json()
    s2 = Signal.model_validate_json(json_str)
    assert s2.signal_type == "test.roundtrip"
    assert s2.data["key"] == "value"


def test_trigger_with_pipeline() -> None:
    t = Trigger(
        trigger_id="t1",
        signal_pattern="motion.*",
        conditions=[TriggerCondition(field="confidence", operator="gte", value=0.8)],
        pipeline=[Processor(processor_type="filter", config={"field": "zone", "operator": "eq", "value": "hallway"})],
        reaction=Reaction(reaction_type="tool_call", config={"tool": "notify"}),
    )
    assert t.trigger_id == "t1"
    assert len(t.conditions) == 1
    assert len(t.pipeline) == 1
    assert t.reaction is not None
    assert t.reaction.reaction_type == "tool_call"


def test_trigger_defaults() -> None:
    t = Trigger(trigger_id="t2", signal_pattern="*")
    assert t.cooldown_seconds == 0
    assert t.enabled is True
    assert t.pipeline == []
    assert t.reaction is None


def test_watcher_config() -> None:
    w = WatcherConfig(
        watcher_type="timer",
        config={"schedules": [{"timer_id": "x", "interval_seconds": 60}]},
    )
    assert w.watcher_type == "timer"
    assert len(w.config["schedules"]) == 1


def test_condition_operators() -> None:
    for op in ("eq", "ne", "gt", "lt", "gte", "lte", "in", "contains", "matches"):
        c = TriggerCondition(field="x", operator=op, value=1)
        assert c.operator == op
