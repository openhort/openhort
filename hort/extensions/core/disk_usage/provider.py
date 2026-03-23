"""Disk Usage plugin — tracks partition usage across all mountpoints."""

from __future__ import annotations

import time
from typing import Any

from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin


class DiskUsage(PluginBase, ScheduledMixin, MCPMixin):
    """Polls disk partition usage and stores it for the dashboard and AI."""

    def activate(self, config: dict[str, Any]) -> None:
        self._latest: dict[str, Any] = {}
        self.log.info("Disk usage monitor activated")

    def deactivate(self) -> None:
        self.log.info("Disk usage monitor deactivated")

    def get_status(self) -> dict[str, Any]:
        """Return in-memory disk data."""
        return {"latest": self._latest}

    # ===== Scheduler =====

    def poll_disks(self) -> None:
        """Polls disk partitions and usage. Runs in executor thread."""
        import psutil

        now = time.time()
        partitions: list[dict[str, Any]] = []

        if self.config.is_feature_enabled("partitions"):
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                except (PermissionError, OSError):
                    continue
                partitions.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": usage.percent,
                })

        self._latest = {
            "timestamp": now,
            "partitions": partitions,
        }

    # ===== MCP =====

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="get_disk_usage",
                description="Get disk usage for all partitions",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="get_partition_details",
                description="Get detailed disk usage for a specific mountpoint",
                input_schema={
                    "type": "object",
                    "properties": {
                        "mountpoint": {
                            "type": "string",
                            "description": "Mountpoint path (e.g. '/' or '/home')",
                        },
                    },
                    "required": ["mountpoint"],
                },
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        if tool_name == "get_disk_usage":
            data = self._latest
            if not data:
                return MCPToolResult(
                    content=[{"type": "text", "text": "No disk data available yet"}]
                )
            lines = []
            for p in data.get("partitions", []):
                lines.append(
                    f"{p['device']} on {p['mountpoint']} ({p['fstype']}): "
                    f"{p['used_gb']}/{p['total_gb']} GB ({p['percent']}%)"
                )
            if not lines:
                lines.append("No partitions found")
            return MCPToolResult(
                content=[{"type": "text", "text": "\n".join(lines)}]
            )

        elif tool_name == "get_partition_details":
            mountpoint = arguments.get("mountpoint", "/")
            data = self._latest
            if not data:
                return MCPToolResult(
                    content=[{"type": "text", "text": "No disk data available yet"}]
                )
            for p in data.get("partitions", []):
                if p["mountpoint"] == mountpoint:
                    lines = [
                        f"Device: {p['device']}",
                        f"Mountpoint: {p['mountpoint']}",
                        f"Filesystem: {p['fstype']}",
                        f"Total: {p['total_gb']} GB",
                        f"Used: {p['used_gb']} GB ({p['percent']}%)",
                        f"Free: {p['free_gb']} GB",
                    ]
                    return MCPToolResult(
                        content=[{"type": "text", "text": "\n".join(lines)}]
                    )
            return MCPToolResult(
                content=[{
                    "type": "text",
                    "text": f"Mountpoint '{mountpoint}' not found. "
                    f"Available: {', '.join(p['mountpoint'] for p in data.get('partitions', []))}",
                }],
                is_error=True,
            )

        return MCPToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            is_error=True,
        )
