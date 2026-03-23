"""Network Monitor plugin — tracks interface status and bandwidth usage."""

from __future__ import annotations

import time
from typing import Any

from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin


class NetworkMonitor(PluginBase, ScheduledMixin, MCPMixin):
    """Polls network interface counters and stores bandwidth metrics."""

    def activate(self, config: dict[str, Any]) -> None:
        self._prev_counters: dict[str, dict[str, int]] = {}
        self._prev_time: float = 0.0
        self._latest: dict[str, Any] = {}
        self._history: list[dict[str, Any]] = []
        self.log.info("Network monitor activated")

    def deactivate(self) -> None:
        self.log.info("Network monitor deactivated")

    def get_status(self) -> dict[str, Any]:
        """Return in-memory network data."""
        return {"latest": self._latest, "history": self._history[-60:]}

    # ===== Scheduler =====

    def poll_network(self) -> None:
        """Polls network interface counters. Runs in executor thread."""
        import psutil

        now = time.time()
        metrics: dict[str, Any] = {"timestamp": now}
        interfaces: list[dict[str, Any]] = []

        # Get IP addresses per interface
        addrs = psutil.net_if_addrs()
        # Get I/O counters per interface
        counters = psutil.net_io_counters(pernic=True)

        elapsed = now - self._prev_time if self._prev_time > 0 else 0.0
        total_up_bps = 0.0
        total_down_bps = 0.0

        for iface, cnt in counters.items():
            # Skip loopback
            if iface.startswith("lo"):
                continue

            iface_info: dict[str, Any] = {
                "name": iface,
                "bytes_sent": cnt.bytes_sent,
                "bytes_recv": cnt.bytes_recv,
                "packets_sent": cnt.packets_sent,
                "packets_recv": cnt.packets_recv,
            }

            # Collect IPv4/IPv6 addresses
            ips: list[str] = []
            if iface in addrs:
                for addr in addrs[iface]:
                    if addr.family.name in ("AF_INET", "AF_INET6"):
                        ips.append(addr.address)
            iface_info["ips"] = ips

            # Calculate bandwidth delta
            if self.config.is_feature_enabled("bandwidth") and elapsed > 0:
                prev = self._prev_counters.get(iface)
                if prev:
                    sent_delta = cnt.bytes_sent - prev["bytes_sent"]
                    recv_delta = cnt.bytes_recv - prev["bytes_recv"]
                    up_bps = sent_delta / elapsed
                    down_bps = recv_delta / elapsed
                    iface_info["upload_bps"] = round(up_bps, 1)
                    iface_info["download_bps"] = round(down_bps, 1)
                    total_up_bps += up_bps
                    total_down_bps += down_bps

            interfaces.append(iface_info)

        # Update previous counters for next delta
        self._prev_counters = {
            iface: {"bytes_sent": cnt.bytes_sent, "bytes_recv": cnt.bytes_recv}
            for iface, cnt in counters.items()
        }
        self._prev_time = now

        if self.config.is_feature_enabled("interfaces"):
            metrics["interfaces"] = interfaces

        if self.config.is_feature_enabled("bandwidth"):
            metrics["total_upload_bps"] = round(total_up_bps, 1)
            metrics["total_download_bps"] = round(total_down_bps, 1)

        # Store latest + append to history (in-memory only)
        self._latest = metrics
        self._history.append(metrics)
        # Keep last 60 entries (5 min at 5s interval)
        if len(self._history) > 60:
            self._history = self._history[-60:]

    # ===== MCP =====

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="get_network_status",
                description="Get current network interfaces, IP addresses, and bandwidth usage",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="get_network_history",
                description="Get recent network bandwidth history (last 5 minutes)",
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max entries to return", "default": 30}
                }},
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        if tool_name == "get_network_status":
            data = self._latest
            if not data:
                return MCPToolResult(content=[{"type": "text", "text": "No network data available yet"}])
            lines = []
            up = data.get("total_upload_bps", 0)
            down = data.get("total_download_bps", 0)
            lines.append(f"Total Upload: {_format_speed(up)}")
            lines.append(f"Total Download: {_format_speed(down)}")
            for iface in data.get("interfaces", []):
                ips_str = ", ".join(iface.get("ips", [])) or "no IP"
                bw = ""
                if "upload_bps" in iface:
                    bw = f" (up: {_format_speed(iface['upload_bps'])}, down: {_format_speed(iface['download_bps'])})"
                lines.append(f"  {iface['name']}: {ips_str}{bw}")
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])

        elif tool_name == "get_network_history":
            limit = arguments.get("limit", 30)
            entries = list(reversed(self._history[-limit:]))
            return MCPToolResult(content=[{"type": "text", "text": f"{len(entries)} entries:\n" + "\n".join(
                f"  UP:{_format_speed(e.get('total_upload_bps', 0))} DOWN:{_format_speed(e.get('total_download_bps', 0))}"
                for e in entries
            )}])

        return MCPToolResult(content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}], is_error=True)


def _format_speed(bps: float) -> str:
    """Format bytes-per-second into a human-readable speed string."""
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    elif bps >= 1024:
        return f"{bps / 1024:.1f} KB/s"
    else:
        return f"{bps:.0f} B/s"
