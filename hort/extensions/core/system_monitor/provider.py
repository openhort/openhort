"""System Monitor llming — tracks CPU, memory, and disk metrics.

Migrated from v1 (PluginBase + 4 mixins) to v2 (LlmingBase, no mixins).
All powers declared in a single get_powers() method.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from hort.llming import LlmingBase, Power, PowerType


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine from sync context, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    else:
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()


class SystemMonitor(LlmingBase):
    """Polls system metrics and stores them for the dashboard and AI."""

    # In-memory live data (never written to disk for metrics)
    _latest: dict[str, Any] = {}
    _history: list[dict[str, Any]] = []

    def activate(self, config: dict[str, Any]) -> None:
        self._latest = {}
        self._history = []
        self.log.info("System monitor activated")

    def deactivate(self) -> None:
        self.log.info("System monitor deactivated")

    # ── Powers ──

    def get_powers(self) -> list[Power]:
        return [
            # MCP tools — for AI agents
            Power(
                name="get_system_metrics",
                type=PowerType.MCP,
                description="Get current CPU, memory, and disk usage metrics",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="get_system_history",
                type=PowerType.MCP,
                description="Get recent system metrics history (last 5 minutes)",
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max entries to return", "default": 30}
                }},
            ),
            # Slash commands — for humans via Telegram/Wire
            Power(
                name="cpu",
                type=PowerType.COMMAND,
                description="Current CPU, memory, disk usage",
            ),
            Power(
                name="health",
                type=PowerType.COMMAND,
                description="Full system health report",
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        # MCP tools
        if name == "get_system_metrics":
            return self._format_metrics()

        if name == "get_system_history":
            limit = args.get("limit", 30)
            entries = list(reversed(self._history[-limit:]))
            text = f"{len(entries)} entries:\n" + "\n".join(
                f"  CPU:{e.get('cpu_percent', '?')}% MEM:{e.get('mem_percent', '?')}% DISK:{e.get('disk_percent', '?')}%"
                for e in entries
            )
            return {"content": [{"type": "text", "text": text}]}

        # Slash commands
        if name == "cpu":
            data = self._latest
            if not data:
                return "No metrics available yet."
            cpu = data.get("cpu_percent", "?")
            mem = data.get("mem_percent", "?")
            disk = data.get("disk_percent", "?")
            return f"CPU: {cpu}%  MEM: {mem}%  DISK: {disk}%"

        if name == "health":
            return self._get_health_summary()

        return {"error": f"Unknown power: {name}"}

    # ── Pulse ──

    def get_pulse(self) -> dict[str, Any]:
        """Return in-memory status for thumbnail rendering."""
        return {"latest": self._latest, "history": self._history[-60:]}

    def get_pulse_channels(self) -> list[str]:
        return ["cpu_spike", "memory_warning", "disk_full"]

    # ── Scheduled job (declared in manifest, called by framework) ──

    def poll_metrics(self) -> None:
        """Polls CPU, memory, and disk metrics. Runs in executor thread."""
        import psutil

        now = time.time()
        metrics: dict[str, Any] = {"timestamp": now}

        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        metrics["cpu_count"] = psutil.cpu_count()
        metrics["cpu_freq_mhz"] = round(psutil.cpu_freq().current) if psutil.cpu_freq() else 0
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for _name, entries in temps.items():
                    if entries:
                        metrics["cpu_temp_c"] = round(entries[0].current, 1)
                        break
        except (AttributeError, RuntimeError):
            pass

        mem = psutil.virtual_memory()
        metrics["mem_total_gb"] = round(mem.total / (1024**3), 1)
        metrics["mem_used_gb"] = round(mem.used / (1024**3), 1)
        metrics["mem_percent"] = mem.percent
        swap = psutil.swap_memory()
        metrics["swap_used_gb"] = round(swap.used / (1024**3), 1)
        metrics["swap_percent"] = swap.percent

        import os
        disk_path = "/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else "/"
        disk = psutil.disk_usage(disk_path)
        metrics["disk_total_gb"] = round(disk.total / (1024**3), 1)
        metrics["disk_used_gb"] = round(disk.used / (1024**3), 1)
        metrics["disk_percent"] = disk.percent

        self._latest = metrics
        self._history.append(metrics)
        if len(self._history) > 60:
            self._history = self._history[-60:]

    # ── Internal helpers ──

    def _format_metrics(self) -> dict[str, Any]:
        """Format latest metrics as MCP content blocks."""
        data = self._latest
        if not data:
            return {"content": [{"type": "text", "text": "No metrics available yet"}]}
        lines = []
        if "cpu_percent" in data:
            lines.append(f"CPU: {data['cpu_percent']}% ({data.get('cpu_count', '?')} cores, {data.get('cpu_freq_mhz', '?')} MHz)")
        if "cpu_temp_c" in data:
            lines.append(f"CPU Temperature: {data['cpu_temp_c']}°C")
        if "mem_percent" in data:
            lines.append(f"Memory: {data['mem_used_gb']}/{data['mem_total_gb']} GB ({data['mem_percent']}%)")
        if "disk_percent" in data:
            lines.append(f"Disk: {data['disk_used_gb']}/{data['disk_total_gb']} GB ({data['disk_percent']}%)")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    def _get_health_summary(self) -> str:
        """Full health report text."""
        data = self._latest
        if not data:
            return "No system metrics available yet. The monitor is starting up."
        lines = [
            "System Health Report (polled every 5 seconds)",
            f"CPU: {data.get('cpu_percent', '?')}% usage, {data.get('cpu_count', '?')} cores",
        ]
        if "cpu_temp_c" in data:
            lines.append(f"CPU Temperature: {data['cpu_temp_c']}°C")
        lines.extend([
            f"Memory: {data.get('mem_used_gb', '?')}/{data.get('mem_total_gb', '?')} GB ({data.get('mem_percent', '?')}%)",
            f"Disk: {data.get('disk_used_gb', '?')}/{data.get('disk_total_gb', '?')} GB ({data.get('disk_percent', '?')}%)",
        ])
        return "\n".join(lines)
