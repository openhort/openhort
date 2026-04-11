"""Interactive chat loop for llming-models — local and container modes."""

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

if TYPE_CHECKING:
    from hort.sandbox import Session
    from hort.sandbox.mcp import McpConfig
    from hort.sandbox.mcp_proxy import ProxyManager

_DOCKERFILE_DIR = str(Path(__file__).resolve().parent)
_IMAGE = "openhort-sandbox-llming:latest"


def _setup_mcp(
    mcp_config: McpConfig,
    container: bool,
    tmpdir: str,
    session: Session | None,
) -> tuple[str | None, list[str], ProxyManager | None]:
    """Set up MCP servers — identical to claude_code's approach."""
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
            "/workspace/.llming-mcp.json", json.dumps(mcp_json),
        )
        config_path = "/workspace/.llming-mcp.json"
    else:
        config_path = os.path.join(tmpdir, ".llming-mcp.json")
        with open(config_path, "w") as f:
            json.dump(mcp_json, f)

    return config_path, compute_disallowed_tools(direct), proxy_mgr


def _container_turn(
    session: Session,
    message: str,
    model: str,
    system_prompt: str | None,
) -> str:
    """Execute one turn inside the container, return response text."""
    cmd = [
        "python3", "-m", "llmings.llms.llming_models_ext.container_entry",
        "--model", model,
    ]
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    cmd.append(message)

    proc = session.exec_streaming(cmd)
    assert proc.stdout is not None

    parts: list[str] = []
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "text":
            chunk = event.get("content", "")
            sys.stdout.write(chunk)
            sys.stdout.flush()
            parts.append(chunk)

    proc.wait()
    return "".join(parts)


def run_chat(
    *,
    model: str = "claude_sonnet",
    system_prompt: str | None = None,
    api_key: str | None = None,
    container: bool = False,
    memory: str | None = None,
    cpus: float | None = None,
    disk: str | None = None,
    mcp_config: McpConfig | None = None,
    resume_session: str | None = None,
    resume_conversation: str | None = None,
    max_budget: float | None = None,
) -> None:
    """Interactive chat loop — local or container mode."""
    from hort.llm.history import ConversationStore

    store = ConversationStore()
    session: Session | None = None
    proxy_mgr: ProxyManager | None = None
    tmpdir = tempfile.mkdtemp(prefix="llming-chat-")
    usage = LLMUsage(budget_limit=max_budget)

    # ── Cleanup expired conversations on startup ────────────────────
    expired = store.cleanup_expired()
    if expired:
        print(f"Cleaned up {len(expired)} expired conversation(s).")

    # ── Container setup ─────────────────────────────────────────────
    if container:
        from hort.sandbox import SessionConfig, SessionManager
        from hort.sandbox.reaper import reap_expired

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not resolved_key:
            print("Error: API key required (--api-key or ANTHROPIC_API_KEY).")
            sys.exit(1)

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
            session.meta.config.secret_env = {"ANTHROPIC_API_KEY": resolved_key}
        else:
            session = mgr.create(SessionConfig(
                image=_IMAGE,
                secret_env={"ANTHROPIC_API_KEY": resolved_key},
                memory=memory, cpus=cpus, disk=disk,
            ))
        session.start()

    # ── MCP setup ───────────────────────────────────────────────────
    mcp_config_path: str | None = None
    disallowed_tools: list[str] = []
    if mcp_config and mcp_config.mcpServers:
        mcp_config_path, disallowed_tools, proxy_mgr = _setup_mcp(
            mcp_config, container, tmpdir, session,
        )

    # ── Local provider ──────────────────────────────────────────────
    provider = None
    if not container:
        from .provider import LlmingProvider
        provider = LlmingProvider(
            model=model, system_prompt=system_prompt,
            store=store, api_key=api_key,
        )

    # ── Conversation tracking ───────────────────────────────────────
    conversation_id = resume_conversation
    if conversation_id:
        conv = store.get(conversation_id)
        if conv is None:
            print(f"Conversation '{conversation_id}' not found.")
            sys.exit(1)
        print(f"Resuming conversation ({len(conv.messages)} messages)")

    # ── UI ──────────────────────────────────────────────────────────
    print(f"\033[1mLLM Chat\033[0m  \033[36m[{model}]\033[0m", end="")
    if container and session:
        print(f"  \033[33m[session {session.id}]\033[0m", end="")
    if max_budget is not None:
        print(f"  \033[33m[budget: ${max_budget:.2f}]\033[0m", end="")
    if mcp_config and mcp_config.mcpServers:
        print(f"  \033[36m[mcp: {', '.join(mcp_config.mcpServers)}]\033[0m", end="")
    print()
    print("Type 'exit' or Ctrl-C to quit.\n")

    def cleanup(sig: int = 0, frame: object = None) -> None:
        print("\n\nGoodbye!")
        if usage.total_cost > 0:
            print(f"Usage: {usage.format_status()}")
        if proxy_mgr:
            proxy_mgr.stop()
        if session:
            session.stop()
            print(f"Session preserved: --session {session.id}")
        if conversation_id:
            print(f"Conversation: --conversation {conversation_id}")
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)

    while True:
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

        print("\033[1;34mllm>\033[0m ", end="", flush=True)

        try:
            if container and session:
                text = _container_turn(session, stripped, model, system_prompt)
                if conversation_id is None:
                    conversation_id = store.create(
                        "llming", model, timeout_minutes=60,
                    )
                store.add_message(conversation_id, "user", stripped)
                store.add_message(conversation_id, "assistant", text)
                # TODO: extract cost from container response once
                # llming-models reports usage in streaming output
                usage.record_turn()
                print()
            else:
                assert provider is not None
                response = provider.send(
                    stripped, conversation_id=conversation_id,
                )
                print(response.text)
                if response.conversation_id:
                    conversation_id = response.conversation_id
                usage.record_turn(
                    cost=response.cost,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
        except Exception as e:
            print(f"\n\033[31mError: {e}\033[0m")
            continue
