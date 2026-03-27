"""Tests for signal watchers (timer, polling)."""

from __future__ import annotations

import asyncio

import pytest

from hort.signals.bus import SignalBus
from hort.signals.models import Signal
from hort.signals.watchers import PollingWatcher, TimerWatcher


@pytest.mark.asyncio
async def test_timer_watcher_emits() -> None:
    bus = SignalBus()
    received: list[Signal] = []

    async def collect(s: Signal) -> None:
        received.append(s)

    bus.subscribe("timer.fired", collect)

    watcher = TimerWatcher({
        "schedules": [
            {"timer_id": "fast", "signal_type": "timer.fired", "interval_seconds": 0.05},
        ],
    })
    await watcher.start(bus, "test-hort")
    await asyncio.sleep(0.15)
    await watcher.stop()

    assert len(received) >= 1
    assert received[0].signal_type == "timer.fired"
    assert received[0].data["timer_id"] == "fast"
    assert received[0].source == "timer/fast"
    assert received[0].hort_id == "test-hort"


@pytest.mark.asyncio
async def test_timer_watcher_multiple_schedules() -> None:
    bus = SignalBus()
    received: list[Signal] = []

    async def collect(s: Signal) -> None:
        received.append(s)

    bus.subscribe("*", collect)

    watcher = TimerWatcher({
        "schedules": [
            {"timer_id": "a", "signal_type": "timer.a", "interval_seconds": 0.05},
            {"timer_id": "b", "signal_type": "timer.b", "interval_seconds": 0.05},
        ],
    })
    await watcher.start(bus, "h1")
    await asyncio.sleep(0.15)
    await watcher.stop()

    types = {s.signal_type for s in received}
    assert "timer.a" in types
    assert "timer.b" in types


@pytest.mark.asyncio
async def test_timer_watcher_stop() -> None:
    bus = SignalBus()
    watcher = TimerWatcher({
        "schedules": [{"timer_id": "x", "interval_seconds": 0.05}],
    })
    await watcher.start(bus, "h1")
    await watcher.stop()
    # Tasks should be cancelled
    assert watcher._tasks == []


@pytest.mark.asyncio
async def test_polling_watcher_emits_on_change() -> None:
    bus = SignalBus()
    received: list[Signal] = []

    async def collect(s: Signal) -> None:
        received.append(s)

    bus.subscribe("resource.changed", collect)

    call_count = 0

    def changing_fn() -> int:
        nonlocal call_count
        call_count += 1
        return call_count  # different value each time

    watcher = PollingWatcher(
        config={"interval_seconds": 0.05, "signal_type": "resource.changed", "source": "poll/test"},
        poll_fn=changing_fn,
    )
    await watcher.start(bus, "h1")
    await asyncio.sleep(0.2)
    await watcher.stop()

    assert len(received) >= 2
    assert received[0].data["value"] == 1
    assert received[0].source == "poll/test"


@pytest.mark.asyncio
async def test_polling_watcher_no_emit_same_value() -> None:
    bus = SignalBus()
    received: list[Signal] = []

    async def collect(s: Signal) -> None:
        received.append(s)

    bus.subscribe("*", collect)

    watcher = PollingWatcher(
        config={"interval_seconds": 0.05, "signal_type": "test.poll"},
        poll_fn=lambda: 42,  # always same value
    )
    await watcher.start(bus, "h1")
    await asyncio.sleep(0.2)
    await watcher.stop()

    # Should emit only once (first change from sentinel to 42)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_polling_watcher_stop() -> None:
    bus = SignalBus()
    watcher = PollingWatcher(
        config={"interval_seconds": 0.05},
        poll_fn=lambda: 1,
    )
    await watcher.start(bus, "h1")
    await watcher.stop()
    assert watcher._task is None
