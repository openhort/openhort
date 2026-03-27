"""Main chat loop — read user input, spawn Claude, display response."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from hort.llm.base import LLMUsage

from .typewriter import typewriter

if TYPE_CHECKING:
    from hort.sandbox import Session
    from hort.sandbox.mcp import McpConfig

_DOCKERFILE_DIR = str(Path(__file__).resolve().parent)
_IMAGE = "openhort-sandbox-claude:latest"


def _setup_mcp(
    mcp_config: McpConfig,
    container: bool,
    tmpdir: str,
    session: Session | None,
) -> tuple[str | None, list[str], "ProxyManager | None"]:
    """Set up MCP servers, proxies, and config file."""
    from hort.sandbox.mcp import (
        build_claude_mcp_json,
        compute_disallowed_tools,
        resolve_servers,
    )
    from hort.sandbox.mcp_proxy import ProxyManager

    direct, proxied = resolve_servers(mcp_config, container)

    proxy_mgr: ProxyManager | None = None
    proxy_urls: dict[str, str] = {}
    if proxied:
        proxy_mgr = ProxyManager()
        proxy_urls = proxy_mgr.start(proxied, container)

    mcp_json = build_claude_mcp_json(direct, proxy_urls)
    if not mcp_json["mcpServers"]:
        return None, [], proxy_mgr

    config_path: str
    if container and session is not None:
        session.write_file(
            "/workspace/.claude-chat-mcp.json", json.dumps(mcp_json),
        )
        config_path = "/workspace/.claude-chat-mcp.json"
    else:
        config_path = os.path.join(tmpdir, ".claude-chat-mcp.json")
        with open(config_path, "w") as f:
            json.dump(mcp_json, f)

    return config_path, compute_disallowed_tools(direct), proxy_mgr


def run_chat(
    model: str | None = None,
    system_prompt: str | None = None,
    container: bool = False,
    memory: str | None = None,
    cpus: float | None = None,
    disk: str | None = None,
    mcp_config: McpConfig | None = None,
    resume_session: str | None = None,
    max_budget: float | None = None,
) -> None:
    """Interactive chat loop using the Claude Code CLI provider."""
    session: Session | None = None
    usage = LLMUsage(budget_limit=max_budget)

    # ── Container setup ─────────────────────────────────────────────
    if container:
        from hort.sandbox import SessionConfig, SessionManager
        from hort.sandbox.reaper import reap_expired

        from .auth import get_oauth_token

        token = get_oauth_token()
        mgr = SessionManager()
        mgr.ensure_base_image()
        if not mgr.image_ready(_IMAGE):
            mgr.build_image(_IMAGE, _DOCKERFILE_DIR)

        reaped = reap_expired(mgr)
        if reaped:
            print(f"Cleaned up {len(reaped)} expired session(s).")

        if resume_session:
            session = mgr.get(resume_session)
            if session is None:
                print(f"Session '{resume_session}' not found.")
                sys.exit(1)
            session.meta.config.secret_env = {"ANTHROPIC_API_KEY": token}
        else:
            session = mgr.create(SessionConfig(
                image=_IMAGE,
                secret_env={"ANTHROPIC_API_KEY": token},
                memory=memory, cpus=cpus, disk=disk,
            ))
        session.start()

    tmpdir = tempfile.mkdtemp(prefix="claude-chat-")

    claude_session_id: str | None = None
    if session and session.meta.user_data.get("claude_session_id"):
        claude_session_id = session.meta.user_data["claude_session_id"]

    # ── MCP setup ───────────────────────────────────────────────────
    mcp_config_path: str | None = None
    disallowed_tools: list[str] = []
    proxy_mgr = None
    if mcp_config and mcp_config.mcpServers:
        mcp_config_path, disallowed_tools, proxy_mgr = _setup_mcp(
            mcp_config, container, tmpdir, session,
        )

    # ── Provider (builds commands) ──────────────────────────────────
    from .provider import ClaudeCodeProvider

    provider = ClaudeCodeProvider(
        model=model, system_prompt=system_prompt, container=container,
        mcp_config_path=mcp_config_path,
        disallowed_tools=disallowed_tools or None,
        max_budget=max_budget,
        session=session, cwd=tmpdir,
    )

    # ── UI ──────────────────────────────────────────────────────────
    print("\033[1mClaude Chat\033[0m", end="")
    if container and session:
        print(f"  \033[33m[session {session.id}]\033[0m", end="")
        limits = [x for x in [
            f"mem={memory}" if memory else "",
            f"cpus={cpus}" if cpus is not None else "",
            f"disk={disk}" if disk else "",
        ] if x]
        if limits:
            print(f"  \033[90m({', '.join(limits)})\033[0m", end="")
    if max_budget is not None:
        print(f"  \033[33m[budget: ${max_budget:.2f}]\033[0m", end="")
    if mcp_config and mcp_config.mcpServers:
        print(f"  \033[36m[mcp: {', '.join(mcp_config.mcpServers)}]\033[0m", end="")
    print()
    if not container:
        print(f"Temp dir: {tmpdir}")
    if model:
        print(f"Model: {model}")
    print("Type 'exit' or Ctrl-C to quit.\n")

    def cleanup(sig: int = 0, frame: object = None) -> None:
        print("\n\nGoodbye!")
        if usage.total_cost > 0:
            print(f"Usage: {usage.format_status()}")
        if proxy_mgr:
            proxy_mgr.stop()
        if session:
            if claude_session_id:
                session.meta.user_data["claude_session_id"] = claude_session_id
            session.stop()
            print(f"Session preserved: --session {session.id}")
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)

    while True:
        # ── Budget check ────────────────────────────────────────────
        if usage.budget_exceeded:
            print(f"\033[31mBudget exhausted: {usage.format_status()}\033[0m")
            cleanup()
            return

        try:
            user_input = input("\033[1;32myou>\033[0m ")
        except (EOFError, KeyboardInterrupt):
            cleanup()
            return

        stripped = user_input.strip()
        if stripped.lower() in ("exit", "quit"):
            cleanup()
            return
        if not stripped:
            continue

        cmd = provider.build_command(stripped, claude_session_id)
        if container and session:
            proc = session.exec_streaming(cmd)
        else:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                cwd=tmpdir,
            )

        print("\033[1;34mclaude>\033[0m ", end="", flush=True)
        meta = typewriter(proc)

        if meta.get("session_id"):
            claude_session_id = meta["session_id"]
            if session:
                session.meta.user_data["claude_session_id"] = claude_session_id
                session._save()

        # Claude CLI reports CUMULATIVE totals — use set_cumulative, not record_turn
        usage.set_cumulative(
            total_cost=meta.get("total_cost_usd", meta.get("cost", 0)),
            total_input_tokens=meta.get("total_input_tokens", 0),
            total_output_tokens=meta.get("total_output_tokens", 0),
        )
