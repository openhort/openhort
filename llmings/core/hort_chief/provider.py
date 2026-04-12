"""Hort Chief — admin commands for container management, sessions, workers.

Reference implementation of @power with subcommands and Pydantic models.
All commands are cleanly declared — no manual string parsing or if/elif dispatch.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from pydantic import Field

from hort.llming import Llming, power, PowerInput, PowerOutput

logger = logging.getLogger(__name__)


# ── Input models ──


class HortDetailRequest(PowerInput):
    """Request details for a specific container."""
    version: int = 1
    container_id: str = Field(description="Container ID or short name")


class WorkerListRequest(PowerInput):
    """No parameters needed."""
    version: int = 1


# ── Output models ──


class ContainerInfo(PowerOutput):
    """Container status information."""
    version: int = 1
    name: str = ""
    image: str = ""
    status: str = ""


class HortInfoResponse(PowerOutput):
    """Hort system overview."""
    version: int = 1
    containers: list[dict] = Field(default_factory=list, description="Running containers")
    llm_executor: str = ""
    sessions: int = 0
    mcp_alive: bool = False


class SessionListResponse(PowerOutput):
    """Active chat sessions."""
    version: int = 1
    sessions: list[dict] = Field(default_factory=list)
    count: int = 0


class HortOverviewResponse(PowerOutput):
    """Full topology overview."""
    version: int = 1
    overview: str = ""


# ── Llming ──


class HortChief(Llming):
    """Hort admin — topology, containers, sessions, workers."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Hort Chief activated")

    # ── MCP tools ──

    @power("hort_overview", description="Get hort topology: containers, llmings, groups, sessions")
    async def hort_overview(self) -> HortOverviewResponse:
        return HortOverviewResponse(overview=self._build_overview())

    @power("list_containers", description="List running sandbox containers with status")
    async def list_containers(self) -> PowerOutput:
        containers = self._get_containers()
        return PowerOutput(message="\n".join(
            f"{c['name']}: {c['status']} ({c['image']})" for c in containers
        ) or "No containers running")

    @power("list_sessions", description="List active viewer/chat sessions")
    async def list_sessions_power(self) -> SessionListResponse:
        sessions = self._get_sessions()
        return SessionListResponse(sessions=sessions, count=len(sessions))

    # ── Slash commands ──

    @power("hort info", description="Container and LLM executor status", command="/hort info", mcp=False)
    async def hort_info(self) -> str:
        containers = self._get_containers()
        lines = ["Hort Container Info"]
        for c in containers:
            lines.append(f"  {c['name']}: {c['status']} ({c['image']})")
        if not containers:
            lines.append("  No containers running")
        try:
            from hort.ext.chat_backend import get_llm_executor
            executor = get_llm_executor()
            if executor:
                state = executor.vault.get("state") if hasattr(executor, "vault") else {}
                lines.append(f"\nLLM: {type(executor).__name__}")
                lines.append(f"  started: {state.get('started', '?')}")
        except Exception:
            pass
        return "\n".join(lines)

    @power("hort restart", description="Restart Claude container and clear sessions", command="/hort restart", mcp=False, admin_only=True)
    async def hort_restart(self) -> str:
        logger.info("Admin requested hort container restart")
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=ohsb-", "-q"],
            capture_output=True, text=True, timeout=5,
        )
        if not result.stdout.strip():
            return "No containers to restart."
        for cid in result.stdout.strip().splitlines():
            subprocess.run(["docker", "restart", cid], capture_output=True, timeout=30)
            logger.info("Container %s restarted by admin", cid.strip())
        try:
            from hort.ext.chat_backend import _shared_manager
            if _shared_manager:
                _shared_manager._sessions.clear()
        except Exception:
            pass
        logger.info("Hort container restarted, sessions cleared")
        return "Container restarted. Sessions cleared."

    @power("hort sessions", description="List active chat sessions", command="/hort sessions", mcp=False, admin_only=True)
    async def hort_sessions(self) -> str:
        try:
            from hort.ext.chat_backend import _shared_manager
            if not _shared_manager:
                return "No chat backend."
            sessions = _shared_manager._sessions
            if not sessions:
                return "No active sessions."
            lines = [f"{len(sessions)} active sessions:"]
            for key, session in sessions.items():
                sid = getattr(session, "_session_id", "?") or "new"
                lines.append(f"  {key}: session={sid[:12]}")
            return "\n".join(lines)
        except Exception:
            return "Could not read sessions."

    @power("horts", description="Sub-hort overview", command="/horts", admin_only=True)
    async def horts_command(self) -> str:
        return self._build_overview()

    @power("hort detail", description="Details for a specific container", command="/hort detail", mcp=False, admin_only=True)
    async def hort_detail(self, req: HortDetailRequest) -> str:
        return self._build_detail(req.container_id)

    @power("workers", description="Show managed worker process status", command="/workers", admin_only=True)
    async def workers_command(self) -> str:
        return self._build_workers_status()

    # ── Internal helpers ──

    def _get_containers(self) -> list[dict[str, str]]:
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

    def _build_overview(self) -> str:
        from hort.hort_config import get_hort_config
        hort_cfg = get_hort_config()
        containers = self._get_containers()
        sessions = self._get_sessions()

        lines = [hort_cfg.name or "openhort", ""]
        if not containers:
            lines.append("No sub-horts running.")
        else:
            lines.append("Sub-horts:")
            for c in containers:
                name = c["name"].replace("ohsb-", "")[:12]
                lines.append(f"  {name}: {c['image']} ({c['status']})")
        if sessions:
            lines.append(f"\nSessions: {len(sessions)}")
        return "\n".join(lines)

    def _build_detail(self, name: str) -> str:
        containers = self._get_containers()
        match = None
        for c in containers:
            short = c["name"].replace("ohsb-", "")[:12]
            if name in c["name"] or name == short:
                match = c
                break
        if not match:
            return f"Container '{name}' not found. Use /horts to list."
        lines = [f"Container: {match['name']}", f"Image: {match['image']}", f"Status: {match['status']}"]
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format",
                 "{{.State.StartedAt}}\t{{.HostConfig.Memory}}\t{{.HostConfig.NanoCpus}}",
                 match["name"]],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split("\t")
                if parts[0]:
                    lines.append(f"Started: {parts[0][:19].replace('T', ' ')}")
                mem = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                if mem:
                    lines.append(f"Memory: {mem // (1024*1024)}MB")
        except Exception:
            pass
        return "\n".join(lines)

    def _build_workers_status(self) -> str:
        import os
        from pathlib import Path

        pid_dir = Path.home() / ".hort" / "pids"
        if not pid_dir.exists():
            pid_dir = Path.home() / ".hort" / "instances" / os.environ.get("HORT_INSTANCE_NAME", "michaels-desktop") / "pids"
        if not pid_dir.exists():
            return "No workers."

        pid_files = list(pid_dir.glob("*.pid"))
        if not pid_files:
            return "No workers."

        lines = ["Workers:"]
        for pf in sorted(pid_files):
            name = pf.stem
            try:
                pid = int(pf.read_text().strip())
            except (ValueError, OSError):
                lines.append(f"  {name}: invalid PID")
                continue
            try:
                os.kill(pid, 0)
                alive = True
            except (OSError, ProcessLookupError):
                alive = False
            status = "running" if alive else "DEAD"
            lines.append(f"  {name} (PID {pid}): {status}")
        return "\n".join(lines)
