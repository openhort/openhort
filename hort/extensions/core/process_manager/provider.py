"""Process Manager plugin — view and manage running processes."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin


class ProcessManager(PluginBase, ScheduledMixin, MCPMixin):
    """Lists processes with CPU/memory usage, allows killing by PID."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Process manager activated")

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

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.store.put("processes", {"list": top, "total": len(procs)}))
        finally:
            loop.close()

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
            data = await self.store.get("processes")
            if not data:
                return MCPToolResult(content=[{"type": "text", "text": "No process data yet"}])
            procs = data.get("list", [])
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
