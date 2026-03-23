"""System Monitor plugin — tracks CPU, memory, and disk metrics."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from hort.ext.connectors import ConnectorCapabilities, ConnectorCommand, ConnectorMixin, ConnectorResponse, IncomingMessage
from hort.ext.documents import DocumentDef, DocumentMixin
from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine from sync context, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # We're in an executor thread called from an async context
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


class SystemMonitor(PluginBase, ScheduledMixin, MCPMixin, DocumentMixin, ConnectorMixin):
    """Polls system metrics and stores them for the dashboard and AI."""

    # In-memory live data (never written to disk for metrics)
    _latest: dict[str, Any] = {}
    _history: list[dict[str, Any]] = []

    def get_status(self) -> dict[str, Any]:
        """Return in-memory status for thumbnail rendering."""
        return {"latest": self._latest, "history": self._history[-60:]}

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("System monitor activated")

    def deactivate(self) -> None:
        self.log.info("System monitor deactivated")

    # ===== Scheduler =====

    def poll_metrics(self) -> None:
        """Polls CPU, memory, and disk metrics. Runs in executor thread."""
        import psutil

        now = time.time()
        metrics: dict[str, Any] = {"timestamp": now}

        if self.config.is_feature_enabled("cpu"):
            metrics["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            metrics["cpu_count"] = psutil.cpu_count()
            metrics["cpu_freq_mhz"] = round(psutil.cpu_freq().current) if psutil.cpu_freq() else 0
            # Temperature (not available on all platforms)
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            metrics["cpu_temp_c"] = round(entries[0].current, 1)
                            break
            except (AttributeError, RuntimeError):
                pass  # macOS doesn't expose temperature via psutil

        if self.config.is_feature_enabled("memory"):
            mem = psutil.virtual_memory()
            metrics["mem_total_gb"] = round(mem.total / (1024**3), 1)
            metrics["mem_used_gb"] = round(mem.used / (1024**3), 1)
            metrics["mem_percent"] = mem.percent
            swap = psutil.swap_memory()
            metrics["swap_used_gb"] = round(swap.used / (1024**3), 1)
            metrics["swap_percent"] = swap.percent

        if self.config.is_feature_enabled("disk"):
            # On macOS, /System/Volumes/Data is the real user data volume
            import os
            disk_path = "/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else "/"
            disk = psutil.disk_usage(disk_path)
            metrics["disk_total_gb"] = round(disk.total / (1024**3), 1)
            metrics["disk_used_gb"] = round(disk.used / (1024**3), 1)
            metrics["disk_percent"] = disk.percent

        # Store latest + history
        # Store in memory (volatile — no disk I/O for live metrics)
        self._latest = metrics
        self._history.append(metrics)
        if len(self._history) > 60:
            self._history = self._history[-60:]

    # ===== MCP =====

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="get_system_metrics",
                description="Get current CPU, memory, and disk usage metrics",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="get_system_history",
                description="Get recent system metrics history (last 5 minutes)",
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max entries to return", "default": 30}
                }},
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        if tool_name == "get_system_metrics":
            data = self._latest
            if not data:
                return MCPToolResult(content=[{"type": "text", "text": "No metrics available yet"}])
            lines = []
            if "cpu_percent" in data:
                lines.append(f"CPU: {data['cpu_percent']}% ({data.get('cpu_count', '?')} cores, {data.get('cpu_freq_mhz', '?')} MHz)")
            if "cpu_temp_c" in data:
                lines.append(f"CPU Temperature: {data['cpu_temp_c']}°C")
            if "mem_percent" in data:
                lines.append(f"Memory: {data['mem_used_gb']}/{data['mem_total_gb']} GB ({data['mem_percent']}%)")
            if "disk_percent" in data:
                lines.append(f"Disk: {data['disk_used_gb']}/{data['disk_total_gb']} GB ({data['disk_percent']}%)")
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])

        elif tool_name == "get_system_history":
            limit = arguments.get("limit", 30)
            entries = list(reversed(self._history[-limit:]))
            return MCPToolResult(content=[{"type": "text", "text": f"{len(entries)} entries:\n" + "\n".join(
                f"  CPU:{e.get('cpu_percent', '?')}% MEM:{e.get('mem_percent', '?')}% DISK:{e.get('disk_percent', '?')}%"
                for e in entries
            )}])

        return MCPToolResult(content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}], is_error=True)

    # ===== Documents =====

    def get_documents(self) -> list[DocumentDef]:
        return [
            DocumentDef(
                uri="plugin://system-monitor/health-summary",
                name="System Health Summary",
                description="Current CPU, memory, and disk status",
                content_fn="get_health_summary",
            ),
        ]

    def get_health_summary(self) -> str:
        data = self._latest
        if not data:
            return "No system metrics available yet. The monitor is starting up."
        lines = [
            f"System Health Report (polled every 5 seconds)",
            f"CPU: {data.get('cpu_percent', '?')}% usage, {data.get('cpu_count', '?')} cores",
        ]
        if "cpu_temp_c" in data:
            lines.append(f"CPU Temperature: {data['cpu_temp_c']}°C")
        lines.extend([
            f"Memory: {data.get('mem_used_gb', '?')}/{data.get('mem_total_gb', '?')} GB ({data.get('mem_percent', '?')}%)",
            f"Disk: {data.get('disk_used_gb', '?')}/{data.get('disk_total_gb', '?')} GB ({data.get('disk_percent', '?')}%)",
        ])
        return "\n".join(lines)

    # ===== Connector =====

    def get_connector_commands(self) -> list[ConnectorCommand]:
        return [
            ConnectorCommand(name="cpu", description="Current CPU, memory, disk usage", plugin_id="system-monitor"),
            ConnectorCommand(name="health", description="Full system health report", plugin_id="system-monitor"),
        ]

    async def handle_connector_command(
        self, command: str, message: IncomingMessage, capabilities: ConnectorCapabilities
    ) -> ConnectorResponse | None:
        if command == "cpu":
            data = self._latest
            if not data:
                return ConnectorResponse.simple("No metrics available yet.")
            cpu = data.get("cpu_percent", "?")
            mem = data.get("mem_percent", "?")
            disk = data.get("disk_percent", "?")
            return ConnectorResponse.simple(f"CPU: {cpu}%  MEM: {mem}%  DISK: {disk}%")

        if command == "health":
            return ConnectorResponse.simple(self.get_health_summary())

        return None
