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
                description="Show hort topology, containers, llmings, sessions",
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
        """Build the full hort topology text."""
        from hort.hort_config import get_hort_config
        hort_cfg = get_hort_config()

        lines = [f"Hort: {hort_cfg.name or 'unnamed'}"]

        # Containers
        containers = self._get_containers()
        lines.append("")
        if containers:
            lines.append(f"Containers ({len(containers)}):")
            for c in containers:
                lines.append(f"  {c['name']} ({c['image']}) - {c['status']}")
        else:
            lines.append("Containers: none running")

        # Llmings
        if hort_cfg.llmings:
            lines.append("")
            lines.append(f"Llmings ({len(hort_cfg.llmings)}):")
            for name, llm in hort_cfg.llmings.items():
                envoy = " [envoy]" if llm.envoy else ""
                lines.append(f"  {name}: {llm.type}{envoy}")

        # Groups
        if hort_cfg.groups:
            lines.append("")
            lines.append(f"Groups ({len(hort_cfg.groups)}):")
            for name, grp in hort_cfg.groups.items():
                tags = []
                if grp.color:
                    tags.append(grp.color)
                if grp.session:
                    tags.append(f"session:{grp.session}")
                if grp.wire.get("allow_admin"):
                    tags.append("admin")
                detail = f" ({', '.join(tags)})" if tags else ""
                lines.append(f"  {name}{detail}")

        # Users
        if hort_cfg.users:
            lines.append("")
            lines.append(f"Users ({len(hort_cfg.users)}):")
            for name, usr in hort_cfg.users.items():
                lines.append(f"  {name}: {', '.join(usr.groups)}")

        # Sessions
        sessions = self._get_sessions()
        if sessions:
            lines.append("")
            lines.append(f"Sessions ({len(sessions)}):")
            for s in sessions:
                lines.append(f"  {s['id']} {s['type']} {s['ip']}")

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
