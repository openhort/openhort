"""Tests for llming subprocess isolation.

Tests the full lifecycle: spawn subprocess, communicate via IPC,
execute powers, receive pulse updates, clean shutdown.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hort.lifecycle.llming_process import GroupProcess

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "test_llming"
MANIFEST_PATH = str(FIXTURE_DIR / "manifest.json")


@pytest.fixture
async def llming_proc():
    """Start a llming subprocess and yield the process, then stop it."""
    proc = GroupProcess("", {"test-llming": MANIFEST_PATH})
    started = await proc.start()
    assert started, "Subprocess failed to start"
    ready = await proc.wait_ready(timeout=10)
    assert ready, "Subprocess did not become ready"
    yield proc
    await proc.stop()


class TestSubprocessIsolation:
    """Test that llmings run correctly in subprocesses."""

    async def test_subprocess_starts_and_registers_powers(self, llming_proc: GroupProcess) -> None:
        proxy = llming_proc.proxies["test-llming"]
        powers = proxy.get_powers()
        assert len(powers) == 2
        names = {p.name for p in powers}
        assert names == {"echo", "count"}

    async def test_execute_power_echo(self, llming_proc: GroupProcess) -> None:
        proxy = llming_proc.proxies["test-llming"]
        result = await proxy.execute_power("echo", {"text": "hello subprocess"})
        assert result["content"][0]["text"] == "hello subprocess"

    async def test_execute_power_count(self, llming_proc: GroupProcess) -> None:
        proxy = llming_proc.proxies["test-llming"]
        r1 = await proxy.execute_power("count", {})
        r2 = await proxy.execute_power("count", {})
        assert r1["content"][0]["text"] == "1"
        assert r2["content"][0]["text"] == "2"

    async def test_activate_with_config(self, llming_proc: GroupProcess) -> None:
        proxy = llming_proc.proxies["test-llming"]
        await llming_proc.activate_llming("test-llming", {"start_count": 100})
        result = await proxy.execute_power("count", {})
        assert result["content"][0]["text"] == "101"

    async def test_unknown_power_returns_error(self, llming_proc: GroupProcess) -> None:
        proxy = llming_proc.proxies["test-llming"]
        result = await proxy.execute_power("nonexistent", {})
        assert "error" in result

    async def test_clean_shutdown(self) -> None:
        proc = GroupProcess("", {"test-llming": MANIFEST_PATH})
        await proc.start()
        await proc.wait_ready(timeout=10)
        assert proc.running
        await proc.stop()
        assert not proc.running


class TestSubprocessResilience:
    """Test error handling and edge cases."""

    async def test_proxy_works_as_llming(self, llming_proc: GroupProcess) -> None:
        """Proxy passes isinstance(proxy, Llming) check."""
        from hort.llming.base import Llming
        proxy = llming_proc.proxies["test-llming"]
        assert isinstance(proxy, Llming)
        assert proxy.instance_name == "test-llming"

    async def test_proxy_plugin_id(self, llming_proc: GroupProcess) -> None:
        assert llming_proc.proxies["test-llming"].plugin_id == "test-llming"

    async def test_proxy_get_status(self, llming_proc: GroupProcess) -> None:
        """get_status() returns cached pulse (v1 compat)."""
        status = llming_proc.proxies["test-llming"].get_status()
        assert isinstance(status, dict)
