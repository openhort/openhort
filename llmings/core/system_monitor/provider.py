"""System Monitor — tracks CPU, memory, and disk metrics."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from hort.llming import Llming, power, on, PowerInput, PowerOutput, PulseEvent


# ── Data models ──


class MetricsResponse(PowerOutput):
    version: int = 1
    cpu_percent: float = 0
    cpu_count: int = 0
    mem_percent: float = 0
    mem_used_gb: float = 0
    mem_total_gb: float = 0
    disk_percent: float = 0
    disk_used_gb: float = 0
    disk_total_gb: float = 0


class HistoryRequest(PowerInput):
    version: int = 1
    limit: int = 30


class MetricsUpdate(PulseEvent):
    version: int = 1
    cpu_percent: float = 0
    mem_percent: float = 0
    disk_percent: float = 0


# ── Llming ──


class SystemMonitor(Llming):
    """Polls system metrics and stores them for the dashboard and AI."""

    _latest: dict[str, Any] = {}
    _history: list[dict[str, Any]] = []

    def activate(self, config: dict[str, Any]) -> None:
        self._latest = {}
        self._history = []
        self.log.info("System monitor activated")

    @on("tick:slow")
    async def poll_metrics(self, _data: dict) -> None:
        """Poll system metrics every 5s via tick:slow."""
        metrics = await asyncio.to_thread(self._read_metrics)
        self._latest = metrics
        self._history.append(metrics)
        if len(self._history) > 60:
            self._history = self._history[-60:]

        self.vault.set("latest", metrics)
        await self.emit("system_metrics", MetricsUpdate(
            cpu_percent=metrics.get("cpu_percent", 0),
            mem_percent=metrics.get("mem_percent", 0),
            disk_percent=metrics.get("disk_percent", 0),
        ))

    # ── Powers ──

    @power("get_system_metrics", description="Get current CPU, memory, and disk usage metrics")
    async def get_system_metrics(self) -> MetricsResponse:
        if not self._latest:
            return MetricsResponse(code=404, message="No metrics available yet")
        d = self._latest
        return MetricsResponse(
            cpu_percent=d.get("cpu_percent", 0),
            cpu_count=d.get("cpu_count", 0),
            mem_percent=d.get("mem_percent", 0),
            mem_used_gb=d.get("mem_used_gb", 0),
            mem_total_gb=d.get("mem_total_gb", 0),
            disk_percent=d.get("disk_percent", 0),
            disk_used_gb=d.get("disk_used_gb", 0),
            disk_total_gb=d.get("disk_total_gb", 0),
        )

    @power("get_system_history", description="Get recent system metrics history")
    async def get_system_history(self, req: HistoryRequest) -> PowerOutput:
        entries = list(reversed(self._history[-req.limit:]))
        text = f"{len(entries)} entries:\n" + "\n".join(
            f"  CPU:{e.get('cpu_percent', '?')}% MEM:{e.get('mem_percent', '?')}% DISK:{e.get('disk_percent', '?')}%"
            for e in entries
        )
        return PowerOutput(message=text)

    @power("cpu", description="Current CPU, memory, disk usage", command="/cpu")
    async def cpu_command(self) -> str:
        if not self._latest:
            return "No metrics available yet."
        d = self._latest
        return f"CPU: {d.get('cpu_percent', '?')}%  MEM: {d.get('mem_percent', '?')}%  DISK: {d.get('disk_percent', '?')}%"

    @power("health", description="Full system health report", command="/health")
    async def health_command(self) -> str:
        if not self._latest:
            return "No system metrics available yet."
        d = self._latest
        lines = [
            f"CPU: {d.get('cpu_percent', '?')}% ({d.get('cpu_count', '?')} cores)",
            f"Memory: {d.get('mem_used_gb', '?')}/{d.get('mem_total_gb', '?')} GB ({d.get('mem_percent', '?')}%)",
            f"Disk: {d.get('disk_used_gb', '?')}/{d.get('disk_total_gb', '?')} GB ({d.get('disk_percent', '?')}%)",
        ]
        return "\n".join(lines)

    # ── Pulse (UI thumbnail) ──

    def get_pulse(self) -> dict[str, Any]:
        return {"latest": self._latest, "history": self._history[-60:]}

    # ── Internal ──

    @staticmethod
    def _read_metrics() -> dict[str, Any]:
        import os
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

        disk_path = "/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else "/"
        disk = psutil.disk_usage(disk_path)
        metrics["disk_total_gb"] = round(disk.total / (1024**3), 1)
        metrics["disk_used_gb"] = round(disk.used / (1024**3), 1)
        metrics["disk_percent"] = disk.percent

        return metrics
