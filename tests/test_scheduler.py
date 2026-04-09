"""Tests for PluginScheduler."""

from __future__ import annotations

import asyncio

import pytest

from hort.ext.scheduler import JobSpec, PluginScheduler


@pytest.fixture
def scheduler() -> PluginScheduler:
    return PluginScheduler("test-plugin")


class TestPluginScheduler:
    async def test_start_and_stop_job(self, scheduler: PluginScheduler) -> None:
        counter = {"n": 0}

        def increment() -> None:
            counter["n"] += 1

        spec = JobSpec(id="count", fn_name="increment", interval_seconds=0.05)
        scheduler.start_job(spec, increment)
        assert "count" in scheduler.running_jobs
        await asyncio.sleep(0.15)
        scheduler.stop_job("count")
        assert counter["n"] >= 2

    async def test_run_on_activate(self, scheduler: PluginScheduler) -> None:
        counter = {"n": 0}

        def increment() -> None:
            counter["n"] += 1

        spec = JobSpec(
            id="eager", fn_name="x", interval_seconds=10, run_on_activate=True
        )
        scheduler.start_job(spec, increment)
        await asyncio.sleep(0.1)
        scheduler.stop_all()
        assert counter["n"] >= 1

    async def test_stop_all(self, scheduler: PluginScheduler) -> None:
        def noop() -> None:
            pass

        scheduler.start_job(
            JobSpec(id="a", fn_name="x", interval_seconds=1), noop
        )
        scheduler.start_job(
            JobSpec(id="b", fn_name="x", interval_seconds=1), noop
        )
        assert len(scheduler.running_jobs) == 2
        scheduler.stop_all()
        assert len(scheduler.running_jobs) == 0

    async def test_stop_nonexistent_is_noop(self, scheduler: PluginScheduler) -> None:
        scheduler.stop_job("nope")  # should not raise

    async def test_restart_job_replaces(self, scheduler: PluginScheduler) -> None:
        counter_a = {"n": 0}
        counter_b = {"n": 0}

        spec = JobSpec(id="x", fn_name="x", interval_seconds=0.05)
        scheduler.start_job(spec, lambda: counter_a.__setitem__("n", counter_a["n"] + 1))
        await asyncio.sleep(0.08)
        scheduler.start_job(spec, lambda: counter_b.__setitem__("n", counter_b["n"] + 1))
        await asyncio.sleep(0.08)
        scheduler.stop_all()
        # counter_a should have stopped incrementing
        a_final = counter_a["n"]
        assert counter_b["n"] >= 1
        await asyncio.sleep(0.1)
        assert counter_a["n"] == a_final  # no more increments

    async def test_run_on_activate_error_continues(self, scheduler: PluginScheduler) -> None:
        counter = {"n": 0}

        def fail_first() -> None:
            counter["n"] += 1
            if counter["n"] == 1:
                raise RuntimeError("init error")

        spec = JobSpec(id="fail-init", fn_name="x", interval_seconds=0.05, run_on_activate=True)
        scheduler.start_job(spec, fail_first)
        await asyncio.sleep(0.2)
        scheduler.stop_all()
        assert counter["n"] >= 2  # kept running after initial error

    async def test_job_error_doesnt_stop_loop(self, scheduler: PluginScheduler) -> None:
        counter = {"n": 0}

        def flaky() -> None:
            counter["n"] += 1
            if counter["n"] == 1:
                raise ValueError("oops")

        spec = JobSpec(id="flaky", fn_name="x", interval_seconds=0.05)
        scheduler.start_job(spec, flaky)
        await asyncio.sleep(0.2)
        scheduler.stop_all()
        assert counter["n"] >= 2  # kept running after error


