"""Hort Chief — topology, sub-hort status, container overview, session management.

Core llming that provides /horts command across all connectors (Telegram, Wire, etc.)
and MCP tools for programmatic access. Admin-only — requires allow_admin in user's group.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from hort.ext.connectors import ConnectorMixin
from hort.ext.mcp import MCPMixin
from hort.ext.plugin import PluginBase

logger = logging.getLogger(__name__)


class HortChief(PluginBase, ConnectorMixin, MCPMixin):
    """Hort topology and admin overview."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Hort Chief activated")

    # ===== Connector Commands =====

    def get_connector_commands(self) -> list:
        from hort.ext.connectors import ConnectorCommand
        return [
            ConnectorCommand(
                name="horts",
                description="Sub-hort overview. Use /horts <name> for details.",
                plugin_id="hort-chief",
            ),
        ]

    async def handle_connector_command(
        self, command: str, message: Any, capabilities: Any,
    ) -> Any:
        from hort.ext.connectors import ConnectorResponse

        if command == "horts":
            if not self._is_admin(message):
                return ConnectorResponse.simple("Permission denied. Admin access required.")
            try:
                args = (message.text or "").strip().split(maxsplit=1)
                sub_name = args[1].strip() if len(args) > 1 else ""
                if sub_name:
                    text = self._build_detail(sub_name)
                else:
                    text = self._build_overview()
            except Exception:
                logger.exception("Failed to build hort overview")
                text = "Something went wrong."
            return ConnectorResponse.simple(text)

        return None

    # ===== MCP Tools =====

    def get_mcp_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "hort_overview",
                "description": "Get hort topology: containers, llmings, groups, sessions",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_containers",
                "description": "List running sandbox containers with status",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_sessions",
                "description": "List active viewer/chat sessions with connection type",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    async def execute_mcp_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "hort_overview":
            return {"text": self._build_overview()}
        elif name == "list_containers":
            return {"containers": self._get_containers()}
        elif name == "list_sessions":
            return {"sessions": self._get_sessions()}
        return {"error": f"Unknown tool: {name}"}

    # ===== Internal =====

    def _is_admin(self, message: Any) -> bool:
        """Check if the message sender has admin privileges."""
        try:
            from hort.hort_config import get_hort_config
            hort_cfg = get_hort_config()
            username = getattr(message, "username", "") or ""
            # Try telegram match first, then wire
            user_cfg = (
                hort_cfg.get_user_by_match("telegram", username)
                or hort_cfg.get_user_by_match("wire", username)
            )
            if not user_cfg:
                return False
            groups = hort_cfg.get_user_groups(user_cfg)
            return any(g.wire.get("allow_admin") for g in groups)
        except Exception:
            return False

    def _build_overview(self) -> str:
        """Compact sub-hort overview table."""
        from hort.hort_config import get_hort_config
        hort_cfg = get_hort_config()

        containers = self._get_containers()
        sessions = self._get_sessions()

        lines = [f"{hort_cfg.name or 'openhort'}"]
        lines.append("")

        if not containers:
            lines.append("No sub-horts running.")
            lines.append("")
        else:
            # Table header
            lines.append("Sub-horts:")
            lines.append(f"{'Name':<22} {'Image':<20} {'Status':<15}")
            lines.append("-" * 57)
            for c in containers:
                name = c["name"].replace("ohsb-", "")[:12]
                image = c["image"][:20]
                status = c["status"]
                # Shorten "Up X minutes" → "Up Xm"
                status = (status
                          .replace(" minutes", "m")
                          .replace(" hours", "h")
                          .replace(" seconds", "s")
                          .replace("About a ", "~")
                          .replace("About an ", "~"))
                lines.append(f"{name:<22} {image:<20} {status:<15}")
            lines.append("")

        # Active connections
        if sessions:
            lines.append(f"Sessions ({len(sessions)}):")
            for s in sessions:
                lines.append(f"  {s['type']:<6} {s['ip']:<15} {s['id']}")
            lines.append("")

        lines.append("Use /horts <container-id> for details.")
        return "\n".join(lines)

    def _build_detail(self, name: str) -> str:
        """Detailed view of a specific sub-hort."""
        containers = self._get_containers()

        # Match by full name or short ID
        match = None
        for c in containers:
            short = c["name"].replace("ohsb-", "")[:12]
            if name in c["name"] or name == short:
                match = c
                break

        if not match:
            return f"Sub-hort '{name}' not found. Use /horts to list."

        lines = [f"Sub-hort: {match['name']}"]
        lines.append("")
        lines.append(f"  Image:   {match['image']}")
        lines.append(f"  Status:  {match['status']}")

        # Get detailed Docker inspect
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format",
                 '{{.Config.Image}}\t{{.State.StartedAt}}\t'
                 '{{.HostConfig.Memory}}\t{{.HostConfig.NanoCpus}}\t'
                 '{{range .Mounts}}{{.Name}}:{{.Destination}} {{end}}',
                 match["name"]],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split("\t")
                if len(parts) >= 4:
                    started = parts[1][:19].replace("T", " ") if parts[1] else "?"
                    mem_bytes = int(parts[2]) if parts[2].isdigit() else 0
                    mem_mb = mem_bytes // (1024 * 1024) if mem_bytes else 0
                    cpus_nano = int(parts[3]) if parts[3].isdigit() else 0
                    cpus = cpus_nano / 1e9 if cpus_nano else 0
                    mounts = parts[4].strip() if len(parts) > 4 else ""

                    lines.append(f"  Started: {started}")
                    if mem_mb:
                        lines.append(f"  Memory:  {mem_mb}MB")
                    if cpus:
                        lines.append(f"  CPUs:    {cpus:.1f}")
                    if mounts:
                        lines.append(f"  Volumes: {mounts}")
        except Exception:
            pass

        # Health check
        try:
            result = subprocess.run(
                ["docker", "exec", match["name"], "echo", "ok"],
                capture_output=True, text=True, timeout=5,
            )
            healthy = result.returncode == 0
            lines.append(f"  Health:  {'ok' if healthy else 'unhealthy'}")
        except Exception:
            lines.append(f"  Health:  unknown")

        return "\n".join(lines)

    def _get_containers(self) -> list[dict[str, str]]:
        """Get running sandbox containers."""
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=ohsb-", "--format",
                 "{{.Names}}\t{{.Status}}\t{{.Image}}"],
                capture_output=True, text=True, timeout=5,
            )
            containers = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                containers.append({
                    "name": parts[0] if parts else "?",
                    "status": parts[1] if len(parts) > 1 else "?",
                    "image": parts[2].split(":")[0] if len(parts) > 2 else "?",
                })
            return containers
        except Exception:
            return []

    def _get_sessions(self) -> list[dict[str, str]]:
        """Get active sessions from SessionManager."""
        try:
            from hort.session import HortSessionManager
            mgr = HortSessionManager.get()
            sessions = []
            for sid, ctx in mgr.active_contexts().items():
                sessions.append({
                    "id": sid[:8] + "...",
                    "type": ctx.connection_type.value,
                    "ip": ctx.remote_ip,
                })
            return sessions
        except Exception:
            return []
