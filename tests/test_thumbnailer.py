"""Tests for the thumbnail rotation scheduler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from hort.thumbnailer import ThumbnailScheduler


@pytest.fixture(autouse=True)
def _reset():
    ThumbnailScheduler.reset()
    yield
    ThumbnailScheduler.reset()


def test_set_windows() -> None:
    sched = ThumbnailScheduler.get()
    sched.set_windows([
        {"window_id": 1, "target_id": "mac"},
        {"window_id": 2, "target_id": "mac"},
    ])
    assert len(sched._window_ids) == 2


def test_set_windows_removes_gone() -> None:
    sched = ThumbnailScheduler.get()
    sched.set_windows([
        {"window_id": 1}, {"window_id": 2}, {"window_id": 3},
    ])
    assert len(sched._window_ids) == 3
    sched.set_windows([{"window_id": 1}, {"window_id": 3}])
    assert len(sched._window_ids) == 2
    assert 2 not in sched._window_ids


def test_set_windows_adds_new() -> None:
    sched = ThumbnailScheduler.get()
    sched.set_windows([{"window_id": 1}])
    sched.set_windows([{"window_id": 1}, {"window_id": 4}])
    assert len(sched._window_ids) == 2
    assert 4 in sched._window_ids


@pytest.mark.asyncio
async def test_subscribe_unsubscribe() -> None:
    sched = ThumbnailScheduler.get()
    session = AsyncMock()
    sched.subscribe(session)
    assert session in sched._subscribers
    sched.unsubscribe(session)
    assert session not in sched._subscribers


def test_get_cached_empty() -> None:
    sched = ThumbnailScheduler.get()
    assert sched.get_cached(999) is None
    assert sched.get_all_cached() == {}


def test_singleton() -> None:
    a = ThumbnailScheduler.get()
    b = ThumbnailScheduler.get()
    assert a is b


def test_reset() -> None:
    a = ThumbnailScheduler.get()
    ThumbnailScheduler.reset()
    b = ThumbnailScheduler.get()
    assert a is not b
