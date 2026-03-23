"""Process Manager plugin — view and manage running processes."""

from __future__ import annotations

import os
import signal
from typing import Any

from hort.ext.connectors import ConnectorCapabilities, ConnectorCommand, ConnectorMixin, ConnectorResponse, IncomingMessage
from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin


class ProcessManager(PluginBase, ScheduledMixin, MCPMixin, ConnectorMixin):
    """Lists processes with CPU/memory usage, allows killing by PID."""

    def activate(self, config: dict[str, Any]) -> None:
        self._latest: dict[str, Any] = {}
        self.log.info("Process manager activated")

    def get_status(self) -> dict[str, Any]:
        """Return in-memory process data."""
        return {"processes": self._latest}

    def poll_processes(self) -> None:
        """Snapshot top processes by CPU usage."""
        import psutil

        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status", "username"]):
            try:
                info = p.info
                if info and info.get("pid") and info.get("name"):
                    procs.append({
                        "pid": info["pid"],
                        "name": info["name"],
                        "cpu": round(info.get("cpu_percent") or 0, 1),
                        "mem": round(info.get("memory_percent") or 0, 1),
                        "status": info.get("status", ""),
                        "user": info.get("username", ""),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by CPU, keep top 50
        procs.sort(key=lambda p: p["cpu"], reverse=True)
        top = procs[:50]

        self._latest = {"list": top, "total": len(procs)}

    # ===== MCP =====

    def get_mcp_tools(self) -> list[MCPToolDef]:
        tools = [
            MCPToolDef(
                name="list_processes",
                description="List running processes sorted by CPU usage",
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max processes to return", "default": 20},
                    "sort_by": {"type": "string", "enum": ["cpu", "mem", "name"], "default": "cpu"},
                }},
            ),
        ]
        if self.config.is_feature_enabled("kill"):
            tools.append(MCPToolDef(
                name="kill_process",
                description="Kill a process by PID (requires kill feature enabled)",
                input_schema={"type": "object", "properties": {
                    "pid": {"type": "integer", "description": "Process ID to kill"},
                    "force": {"type": "boolean", "description": "Force kill (SIGKILL)", "default": False},
                }, "required": ["pid"]},
            ))
        return tools

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        if tool_name == "list_processes":
            data = self._latest
            if not data:
                return MCPToolResult(content=[{"type": "text", "text": "No process data yet"}])
            procs = list(data.get("list", []))
            limit = arguments.get("limit", 20)
            sort_by = arguments.get("sort_by", "cpu")
            if sort_by == "mem":
                procs.sort(key=lambda p: p["mem"], reverse=True)
            elif sort_by == "name":
                procs.sort(key=lambda p: p["name"].lower())
            lines = [f"{'PID':>7} {'CPU%':>6} {'MEM%':>6} {'STATUS':>10} {'NAME'}"]
            for p in procs[:limit]:
                lines.append(f"{p['pid']:>7} {p['cpu']:>6.1f} {p['mem']:>6.1f} {p['status']:>10} {p['name']}")
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])

        elif tool_name == "kill_process":
            if not self.config.is_feature_enabled("kill"):
                return MCPToolResult(content=[{"type": "text", "text": "Kill feature is disabled"}], is_error=True)
            pid = arguments.get("pid")
            force = arguments.get("force", False)
            if not pid:
                return MCPToolResult(content=[{"type": "text", "text": "PID required"}], is_error=True)
            try:
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)
                return MCPToolResult(content=[{"type": "text", "text": f"Sent {'SIGKILL' if force else 'SIGTERM'} to PID {pid}"}])
            except ProcessLookupError:
                return MCPToolResult(content=[{"type": "text", "text": f"Process {pid} not found"}], is_error=True)
            except PermissionError:
                return MCPToolResult(content=[{"type": "text", "text": f"Permission denied for PID {pid}"}], is_error=True)

        return MCPToolResult(content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}], is_error=True)

    # ===== Connector =====

    def get_connector_commands(self) -> list[ConnectorCommand]:
        return [
            ConnectorCommand(name="processes", description="Top processes by CPU", plugin_id="process-manager"),
            ConnectorCommand(name="kill", description="Kill a process by PID", plugin_id="process-manager"),
        ]

    async def handle_connector_command(
        self, command: str, message: IncomingMessage, capabilities: ConnectorCapabilities
    ) -> ConnectorResponse | None:
        if command == "processes":
            data = self._latest
            if not data:
                return ConnectorResponse.simple("No process data yet.")
            procs = list(data.get("list", []))[:10]
            lines = [f"{'PID':>7} {'CPU%':>6} {'MEM%':>6} {'NAME'}"]
            for p in procs:
                lines.append(f"{p['pid']:>7} {p['cpu']:>6.1f} {p['mem']:>6.1f} {p['name']}")
            return ConnectorResponse.simple("\n".join(lines))

        if command == "kill":
            if not self.config.is_feature_enabled("kill"):
                return ConnectorResponse.simple("Kill feature is disabled.")
            args = message.command_args.strip()
            if not args:
                return ConnectorResponse.simple("Usage: /kill <PID>")
            try:
                pid = int(args.split()[0])
            except ValueError:
                return ConnectorResponse.simple(f"Invalid PID: {args}")
            try:
                os.kill(pid, signal.SIGTERM)
                return ConnectorResponse.simple(f"Sent SIGTERM to PID {pid}.")
            except ProcessLookupError:
                return ConnectorResponse.simple(f"Process {pid} not found.")
            except PermissionError:
                return ConnectorResponse.simple(f"Permission denied for PID {pid}.")

        return None
