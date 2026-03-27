"""Tests for signal processors and pipeline execution."""

from __future__ import annotations

import pytest

from hort.signals.models import Processor, Signal
from hort.signals.processors import (
    evaluate_condition,
    register_processor,
    render_template,
    reset_processor_state,
    run_pipeline,
)


def _sig(**data: object) -> Signal:
    return Signal(signal_type="test", source="unit", hort_id="h1", data=data)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_processor_state()


# ── evaluate_condition ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,op,target,expected",
    [
        (1, "eq", 1, True),
        (1, "eq", 2, False),
        (1, "ne", 2, True),
        (5, "gt", 3, True),
        (5, "gt", 5, False),
        (3, "lt", 5, True),
        (5, "gte", 5, True),
        (5, "lte", 5, True),
        ("a", "in", ["a", "b"], True),
        ("c", "in", ["a", "b"], False),
        ("hello world", "contains", "world", True),
        ("hello", "contains", "xyz", False),
        ("abc123", "matches", r"\d+", True),
        ("abc", "matches", r"\d+", False),
        (None, "gt", 5, False),
    ],
)
def test_evaluate_condition(value: object, op: str, target: object, expected: bool) -> None:
    assert evaluate_condition(value, op, target) == expected


# ── render_template ─────────────────────────────────────────────────


def test_render_template() -> None:
    assert render_template("Hello {name}!", {"name": "World"}) == "Hello World!"


def test_render_template_multiple() -> None:
    result = render_template("{a} + {b}", {"a": "1", "b": "2"})
    assert result == "1 + 2"


def test_render_template_missing_key() -> None:
    assert render_template("{missing}", {"other": "val"}) == "{missing}"


# ── filter processor ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_passes() -> None:
    pipeline = [Processor(processor_type="filter", config={"field": "x", "operator": "eq", "value": 1})]
    result = await run_pipeline(_sig(x=1), pipeline)
    assert result is not None


@pytest.mark.asyncio
async def test_filter_drops() -> None:
    pipeline = [Processor(processor_type="filter", config={"field": "x", "operator": "eq", "value": 1})]
    result = await run_pipeline(_sig(x=2), pipeline)
    assert result is None


@pytest.mark.asyncio
async def test_filter_gte() -> None:
    pipeline = [Processor(processor_type="filter", config={"field": "confidence", "operator": "gte", "value": 0.8})]
    assert await run_pipeline(_sig(confidence=0.9), pipeline) is not None
    assert await run_pipeline(_sig(confidence=0.5), pipeline) is None


# ── transform processor ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_transform_rename() -> None:
    pipeline = [Processor(processor_type="transform", config={"mappings": {"new_name": "{old_name}"}})]
    result = await run_pipeline(_sig(old_name="hello"), pipeline)
    assert result is not None
    assert result.data["new_name"] == "hello"


@pytest.mark.asyncio
async def test_transform_literal() -> None:
    pipeline = [Processor(processor_type="transform", config={"mappings": {"status": "active"}})]
    result = await run_pipeline(_sig(), pipeline)
    assert result is not None
    assert result.data["status"] == "active"


# ── template processor ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_template_renders() -> None:
    pipeline = [Processor(processor_type="template", config={"template": "Zone: {zone}", "output_field": "msg"})]
    result = await run_pipeline(_sig(zone="kitchen"), pipeline)
    assert result is not None
    assert result.data["msg"] == "Zone: kitchen"


# ── debounce processor ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_debounce_suppresses() -> None:
    pipeline = [Processor(processor_type="debounce", config={"window_seconds": 10})]
    r1 = await run_pipeline(_sig(), pipeline)
    r2 = await run_pipeline(_sig(), pipeline)
    assert r1 is not None
    assert r2 is None  # suppressed


@pytest.mark.asyncio
async def test_debounce_different_sources() -> None:
    pipeline = [Processor(processor_type="debounce", config={"window_seconds": 10})]
    s1 = Signal(signal_type="test", source="a", hort_id="h1")
    s2 = Signal(signal_type="test", source="b", hort_id="h1")
    r1 = await run_pipeline(s1, pipeline)
    r2 = await run_pipeline(s2, pipeline)
    assert r1 is not None
    assert r2 is not None  # different source, not suppressed


# ── aggregate processor ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_collects() -> None:
    pipeline = [Processor(processor_type="aggregate", config={"count": 3, "fields": ["value"], "operation": "average"})]
    assert await run_pipeline(_sig(value=10), pipeline) is None
    assert await run_pipeline(_sig(value=20), pipeline) is None
    result = await run_pipeline(_sig(value=30), pipeline)
    assert result is not None
    assert result.data["value"] == 20.0  # average of 10, 20, 30


@pytest.mark.asyncio
async def test_aggregate_sum() -> None:
    pipeline = [Processor(processor_type="aggregate", config={"count": 2, "fields": ["v"], "operation": "sum"})]
    assert await run_pipeline(_sig(v=5), pipeline) is None
    result = await run_pipeline(_sig(v=3), pipeline)
    assert result is not None
    assert result.data["v"] == 8


# ── pipeline chaining ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_chain() -> None:
    pipeline = [
        Processor(processor_type="filter", config={"field": "x", "operator": "gt", "value": 0}),
        Processor(processor_type="template", config={"template": "x={x}", "output_field": "msg"}),
    ]
    result = await run_pipeline(_sig(x=5), pipeline)
    assert result is not None
    assert result.data["msg"] == "x=5"


@pytest.mark.asyncio
async def test_pipeline_drops_early() -> None:
    pipeline = [
        Processor(processor_type="filter", config={"field": "x", "operator": "gt", "value": 10}),
        Processor(processor_type="template", config={"template": "never", "output_field": "msg"}),
    ]
    result = await run_pipeline(_sig(x=1), pipeline)
    assert result is None


@pytest.mark.asyncio
async def test_unknown_processor_drops() -> None:
    pipeline = [Processor(processor_type="nonexistent", config={})]
    result = await run_pipeline(_sig(), pipeline)
    assert result is None


# ── custom processor registration ─────────────────────────────────


@pytest.mark.asyncio
async def test_register_custom_processor() -> None:
    @register_processor("test_double")
    def double(signal: Signal, config: dict) -> Signal | None:
        field = config.get("field", "value")
        if field in signal.data:
            signal.data[field] = signal.data[field] * 2
        return signal

    pipeline = [Processor(processor_type="test_double", config={"field": "n"})]
    result = await run_pipeline(_sig(n=5), pipeline)
    assert result is not None
    assert result.data["n"] == 10
