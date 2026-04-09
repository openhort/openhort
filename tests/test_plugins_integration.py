"""Integration tests for plugins — loads each plugin via the test harness
and verifies backend (jobs, store, MCP) and UI (Playwright screenshots).

Run with: poetry run pytest tests/test_plugins_integration.py -m integration -v
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import time
from pathlib import Path
from typing import Any

import pytest

from hort.ext.file_store import LocalFileStore
from hort.ext.scheduler import PluginScheduler
from hort.ext.store import FilePluginStore
from hort.llming.base import LlmingBase
from hort.llming.pulse import PulseBus

EXTENSIONS_DIR = Path(__file__).parent.parent / "hort" / "extensions" / "core"

PLUGINS = [
    "system_monitor",
    "process_manager",
    "network_monitor",
    "disk_usage",
    "clipboard_history",
]


def load_test_plugin(
    plugin_name: str, tmp_path: Path
) -> tuple[Any, Any]:
    """Load a llming for testing. Returns (instance, store)."""
    plugin_dir = EXTENSIONS_DIR / plugin_name
    manifest_data = json.loads((plugin_dir / "manifest.json").read_text())

    plugin_id = manifest_data["name"]
    store = FilePluginStore(plugin_id, base_dir=tmp_path)
    files = LocalFileStore(plugin_id, base_dir=tmp_path)
    scheduler = PluginScheduler(plugin_id)

    # Load Python module
    entry_point = manifest_data.get("entry_point", "")
    if not entry_point:
        return None, store

    module_name, class_name = entry_point.split(":")
    module_path = plugin_dir / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"test_plugin.{plugin_id}", str(module_path)
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, class_name)
    instance = cls()

    # Inject LlmingBase services
    assert isinstance(instance, LlmingBase)
    instance._instance_name = plugin_id
    instance._class_name = plugin_id
    instance._store = store
    instance._files = files
    instance._scheduler = scheduler
    instance._logger = logging.getLogger(f"test.{plugin_id}")
    instance._pulse_bus = PulseBus.get()
    instance._config = {}
    instance.activate({})

    return instance, store


@pytest.mark.integration
class TestSystemMonitor:
    def test_poll_and_store(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("system_monitor", tmp_path)
        assert instance is not None

        # Run the polling job
        instance.poll_metrics()

        # Check in-memory data (v2 uses get_pulse(), v1 compat get_status())
        status = instance.get_status()
        latest = status["latest"]
        assert latest is not None
        assert "cpu_percent" in latest
        assert "mem_percent" in latest
        assert "disk_percent" in latest
        assert latest["cpu_percent"] >= 0
        assert latest["mem_total_gb"] > 0

    def test_mcp_tools(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("system_monitor", tmp_path)
        # v2 LlmingBase exposes tools via get_mcp_tools() compat layer
        assert isinstance(instance, LlmingBase)

        # Poll first to populate data
        instance.poll_metrics()

        tools = instance.get_mcp_tools()
        assert len(tools) >= 2
        tool_names = [t.name for t in tools]
        assert "get_system_metrics" in tool_names

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                instance.execute_mcp_tool("get_system_metrics", {})
            )
            # v2 compat wraps in MCPToolResult
            assert not result.is_error
            assert len(result.content) > 0
            text = result.content[0]["text"]
            assert "CPU" in text
            assert "Memory" in text
        finally:
            loop.close()


@pytest.mark.integration
class TestProcessManager:
    def test_poll_and_store(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("process_manager", tmp_path)
        assert instance is not None

        instance.poll_processes()

        status = instance.get_status()
        data = status["processes"]
        assert data is not None
        assert "list" in data
        assert len(data["list"]) > 0
        proc = data["list"][0]
        assert "pid" in proc
        assert "name" in proc
        assert "cpu" in proc

    def test_mcp_list(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("process_manager", tmp_path)
        instance.poll_processes()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                instance.execute_mcp_tool("list_processes", {"limit": 5})
            )
            assert not result.is_error
            assert "PID" in result.content[0]["text"]
        finally:
            loop.close()


@pytest.mark.integration
class TestNetworkMonitor:
    def test_poll_and_store(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("network_monitor", tmp_path)
        assert instance is not None

        instance.poll_network()

        status = instance.get_status()
        latest = status["latest"]
        assert latest is not None
        assert "interfaces" in latest
        assert len(latest["interfaces"]) > 0

    def test_mcp_status(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("network_monitor", tmp_path)
        instance.poll_network()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                instance.execute_mcp_tool("get_network_status", {})
            )
            assert not result.is_error
            assert len(result.content[0]["text"]) > 0
        finally:
            loop.close()


@pytest.mark.integration
class TestDiskUsage:
    def test_poll_and_store(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("disk_usage", tmp_path)
        assert instance is not None

        instance.poll_disks()

        status = instance.get_status()
        latest = status["latest"]
        assert latest is not None
        assert "partitions" in latest
        assert len(latest["partitions"]) > 0
        part = latest["partitions"][0]
        assert "mountpoint" in part
        assert "percent" in part

    def test_mcp_disk_usage(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("disk_usage", tmp_path)
        instance.poll_disks()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                instance.execute_mcp_tool("get_disk_usage", {})
            )
            assert not result.is_error
            text = result.content[0]["text"]
            assert "/" in text  # root mountpoint
        finally:
            loop.close()


@pytest.mark.integration
class TestClipboardHistory:
    def test_poll_clipboard(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("clipboard_history", tmp_path)
        assert instance is not None

        # Poll clipboard (captures whatever is currently copied)
        instance.poll_clipboard()

        # Check in-memory cache
        status = instance.get_status()
        assert isinstance(status["clips"], list)

        # Disk persistence should still work
        loop = asyncio.new_event_loop()
        try:
            keys = loop.run_until_complete(ctx.list_keys("clip:"))
            # May or may not have entries depending on clipboard state
            assert isinstance(keys, list)
        finally:
            loop.close()

    def test_mcp_history(self, tmp_path: Path) -> None:
        instance, ctx = load_test_plugin("clipboard_history", tmp_path)
        instance.poll_clipboard()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                instance.execute_mcp_tool("get_clipboard_history", {"limit": 5})
            )
            assert not result.is_error
        finally:
            loop.close()
