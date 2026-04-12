"""Process Manager plugin — view and manage running processes."""

from __future__ import annotations

import os
import signal
from typing import Any

from hort.llming import Llming, Power, PowerType


class ProcessManager(Llming):
    """Lists processes with CPU/memory usage, allows killing by PID."""

    def activate(self, config: dict[str, Any]) -> None:
        self._latest: dict[str, Any] = {}
        self.log.info("Process manager activated")

    def get_pulse(self) -> dict[str, Any]:
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
        self.vault.set("state", {"processes": self._latest})

    # ===== Powers =====

    def get_powers(self) -> list[Power]:
        powers = [
            # MCP tools
            Power(
                name="list_processes",
                type=PowerType.MCP,
                description="List running processes sorted by CPU usage",
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max processes to return", "default": 20},
                    "sort_by": {"type": "string", "enum": ["cpu", "mem", "name"], "default": "cpu"},
                }},
            ),
            # Connector commands
            Power(
                name="processes",
                type=PowerType.COMMAND,
                description="Top processes by CPU",
            ),
        ]
        if self.config.get("kill", True):
            powers.append(Power(
                name="kill_process",
                type=PowerType.MCP,
                description="Kill a process by PID (requires kill feature enabled)",
                input_schema={"type": "object", "properties": {
                    "pid": {"type": "integer", "description": "Process ID to kill"},
                    "force": {"type": "boolean", "description": "Force kill (SIGKILL)", "default": False},
                }, "required": ["pid"]},
            ))
            powers.append(Power(
                name="kill",
                type=PowerType.COMMAND,
                description="Kill a process by PID",
            ))
        return powers

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        # MCP: list_processes
        if name == "list_processes":
            data = self._latest
            if not data:
                return {"content": [{"type": "text", "text": "No process data yet"}]}
            procs = list(data.get("list", []))
            limit = args.get("limit", 20)
            sort_by = args.get("sort_by", "cpu")
            if sort_by == "mem":
                procs.sort(key=lambda p: p["mem"], reverse=True)
            elif sort_by == "name":
                procs.sort(key=lambda p: p["name"].lower())
            lines = [f"{'PID':>7} {'CPU%':>6} {'MEM%':>6} {'STATUS':>10} {'NAME'}"]
            for p in procs[:limit]:
                lines.append(f"{p['pid']:>7} {p['cpu']:>6.1f} {p['mem']:>6.1f} {p['status']:>10} {p['name']}")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        # MCP: kill_process
        if name == "kill_process":
            if not self.config.get("kill", True):
                return {"content": [{"type": "text", "text": "Kill feature is disabled"}], "is_error": True}
            pid = args.get("pid")
            force = args.get("force", False)
            if not pid:
                return {"content": [{"type": "text", "text": "PID required"}], "is_error": True}
            try:
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)
                return {"content": [{"type": "text", "text": f"Sent {'SIGKILL' if force else 'SIGTERM'} to PID {pid}"}]}
            except ProcessLookupError:
                return {"content": [{"type": "text", "text": f"Process {pid} not found"}], "is_error": True}
            except PermissionError:
                return {"content": [{"type": "text", "text": f"Permission denied for PID {pid}"}], "is_error": True}

        # Command: processes
        if name == "processes":
            data = self._latest
            if not data:
                return "No process data yet."
            procs = list(data.get("list", []))[:10]
            lines = [f"{'PID':>7} {'CPU%':>6} {'MEM%':>6} {'NAME'}"]
            for p in procs:
                lines.append(f"{p['pid']:>7} {p['cpu']:>6.1f} {p['mem']:>6.1f} {p['name']}")
            return "\n".join(lines)

        # Command: kill
        if name == "kill":
            if not self.config.get("kill", True):
                return "Kill feature is disabled."
            cmd_args = args.get("args", "").strip()
            if not cmd_args:
                return "Usage: /kill <PID>"
            try:
                pid = int(cmd_args.split()[0])
            except ValueError:
                return f"Invalid PID: {cmd_args}"
            try:
                os.kill(pid, signal.SIGTERM)
                return f"Sent SIGTERM to PID {pid}."
            except ProcessLookupError:
                return f"Process {pid} not found."
            except PermissionError:
                return f"Permission denied for PID {pid}."

        return {"error": f"Unknown power: {name}"}
