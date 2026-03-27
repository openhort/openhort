"""Tests for the SignalBus pub/sub router."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from hort.signals.bus import SignalBus, _matches
from hort.signals.models import Signal


def _sig(signal_type: str = "test", source: str = "unit", **data: object) -> Signal:
    return Signal(signal_type=signal_type, source=source, hort_id="h1", data=data)


# ── Pattern matching ────────────────────────────────────────────────


def test_matches_exact() -> None:
    assert _matches("motion.detected", "motion.detected")


def test_matches_wildcard_tail() -> None:
    assert _matches("motion.*", "motion.detected")
    assert _matches("motion.*", "motion.cleared")


def test_matches_wildcard_head() -> None:
    assert _matches("*.state_changed", "light.state_changed")
    assert _matches("*.state_changed", "washer.state_changed")


def test_matches_star_all() -> None:
    assert _matches("*", "anything.at.all")


def test_no_match() -> None:
    assert not _matches("motion.*", "washer.done")


# ── Emit and subscribe ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_routes_to_matching() -> None:
    bus = SignalBus()
    received: list[Signal] = []
    bus.subscribe("motion.*", lambda s: _append(received, s))
    await bus.emit(_sig("motion.detected"))
    assert len(received) == 1
    assert received[0].signal_type == "motion.detected"


@pytest.mark.asyncio
async def test_emit_no_match() -> None:
    bus = SignalBus()
    received: list[Signal] = []
    bus.subscribe("washer.*", lambda s: _append(received, s))
    await bus.emit(_sig("motion.detected"))
    assert len(received) == 0


@pytest.mark.asyncio
async def test_multiple_subscribers() -> None:
    bus = SignalBus()
    r1: list[Signal] = []
    r2: list[Signal] = []
    bus.subscribe("test", lambda s: _append(r1, s))
    bus.subscribe("test", lambda s: _append(r2, s))
    await bus.emit(_sig("test"))
    assert len(r1) == 1
    assert len(r2) == 1


@pytest.mark.asyncio
async def test_unsubscribe() -> None:
    bus = SignalBus()
    received: list[Signal] = []
    sub_id = bus.subscribe("test", lambda s: _append(received, s))
    bus.unsubscribe(sub_id)
    await bus.emit(_sig("test"))
    assert len(received) == 0


@pytest.mark.asyncio
async def test_subscriber_error_does_not_break_others() -> None:
    bus = SignalBus()
    received: list[Signal] = []

    async def bad_callback(s: Signal) -> None:
        raise ValueError("boom")

    bus.subscribe("test", bad_callback)
    bus.subscribe("test", lambda s: _append(received, s))
    await bus.emit(_sig("test"))
    assert len(received) == 1  # second subscriber still got it


@pytest.mark.asyncio
async def test_emit_empty_bus() -> None:
    bus = SignalBus()
    await bus.emit(_sig("test"))  # should not raise


# ── Replay ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay() -> None:
    bus = SignalBus()
    before = datetime.now(timezone.utc)
    await bus.emit(_sig("a"))
    await bus.emit(_sig("b"))
    result = await bus.replay("*", before)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_replay_filter_by_type() -> None:
    bus = SignalBus()
    before = datetime.now(timezone.utc)
    await bus.emit(_sig("motion.detected"))
    await bus.emit(_sig("washer.done"))
    result = await bus.replay("motion.*", before)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_buffer_max_size() -> None:
    bus = SignalBus(buffer_size=5)
    for i in range(10):
        await bus.emit(_sig(f"sig.{i}"))
    assert bus.buffer_size == 5


def test_subscriber_count() -> None:
    bus = SignalBus()
    assert bus.subscriber_count == 0
    s1 = bus.subscribe("a", lambda s: asyncio.sleep(0))
    assert bus.subscriber_count == 1
    bus.unsubscribe(s1)
    assert bus.subscriber_count == 0


# ── Helper ──────────────────────────────────────────────────────────


async def _append(lst: list[Signal], s: Signal) -> None:
    lst.append(s)
