"""Entry point: poetry run python -m llmings.llms.llming_api"""

from __future__ import annotations

import sys


def _list_sessions() -> None:
    from hort.sandbox import SessionManager
    mgr = SessionManager()
    sessions = mgr.list_sessions()
    if not sessions:
        print("No sessions.")
        return
    print(f"{'ID':<14} {'Status':<10} {'Created':<20} {'Last Active':<20} {'Image'}")
    print("-" * 90)
    for s in sessions:
        status = "running" if s.is_running() else (
            "stopped" if s.container_exists() else "orphaned"
        )
        created = s.meta.created_at[:19].replace("T", " ")
        active = s.meta.last_active[:19].replace("T", " ")
        image = s.meta.config.image.split("/")[-1]
        print(f"{s.id:<14} {status:<10} {created:<20} {active:<20} {image}")


def _list_conversations() -> None:
    from hort.llm.history import ConversationStore
    store = ConversationStore()
    convos = store.list_conversations()
    if not convos:
        print("No conversations.")
        return
    print(f"{'ID':<14} {'Provider':<10} {'Model':<20} {'Messages':<10} {'Last Active'}")
    print("-" * 80)
    for c in convos:
        active = c.last_active[:19].replace("T", " ")
        print(f"{c.id:<14} {c.provider:<10} {c.model:<20} {len(c.messages):<10} {active}")


def _cleanup() -> None:
    from hort.llm.history import ConversationStore
    from hort.sandbox import SessionManager
    from hort.sandbox.reaper import reap
    mgr = SessionManager()
    destroyed = reap(mgr, max_sessions=20, max_bytes=5 * 1024**3)
    conv_destroyed = ConversationStore().cleanup_expired()
    total = len(destroyed) + len(conv_destroyed)
    if total:
        parts = []
        if destroyed:
            parts.append(f"{len(destroyed)} session(s)")
        if conv_destroyed:
            parts.append(f"{len(conv_destroyed)} conversation(s)")
        print(f"Cleaned up {', '.join(parts)}.")
    else:
        print("Nothing to clean up.")


def main() -> None:
    import argparse

    from hort.sandbox.mcp import McpConfig, load_mcp_config, parse_inline_mcp

    from .chat import run_chat

    parser = argparse.ArgumentParser(description="Chat with an LLM via API")
    parser.add_argument("--model", "-m", default="claude_sonnet",
                        help="Model (e.g. claude_sonnet, claude_haiku, gpt-4o)")
    parser.add_argument("--system", "-s", dest="system_prompt",
                        help="System prompt")
    parser.add_argument("--api-key", help="API key (or set ANTHROPIC_API_KEY)")

    # Container mode
    parser.add_argument("--container", "-c", action="store_true",
                        help="Run inside a Docker sandbox")
    parser.add_argument("--memory", help="Container memory limit (e.g. 512m)")
    parser.add_argument("--cpus", type=float, help="Container CPU limit")
    parser.add_argument("--disk", help="Container disk limit (e.g. 1g)")
    parser.add_argument("--session", help="Resume a sandbox session by ID")
    parser.add_argument("--max-budget", type=float,
                        help="Maximum USD to spend (e.g. 2.00)")

    # MCP
    parser.add_argument("--mcp", action="append", default=[],
                        help="Add MCP: name=command [args...]")
    parser.add_argument("--mcp-config", dest="mcp_config_file",
                        help="Path to MCP config JSON")

    # Conversation
    parser.add_argument("--conversation", help="Resume a conversation by ID")

    # Management
    parser.add_argument("--list-sessions", action="store_true")
    parser.add_argument("--list-conversations", action="store_true")
    parser.add_argument("--destroy-session", metavar="ID")
    parser.add_argument("--cleanup", action="store_true")

    args = parser.parse_args()

    if args.list_sessions:
        _list_sessions()
        return
    if args.list_conversations:
        _list_conversations()
        return
    if args.destroy_session:
        from hort.sandbox import SessionManager
        mgr = SessionManager()
        if mgr.destroy(args.destroy_session):
            print(f"Session {args.destroy_session} destroyed.")
        else:
            print(f"Session {args.destroy_session} not found.")
            sys.exit(1)
        return
    if args.cleanup:
        _cleanup()
        return

    if (args.memory or args.cpus or args.disk) and not args.container:
        parser.error("--memory, --cpus, --disk require --container")
    if args.session and not args.container:
        parser.error("--session requires --container")

    mcp_config = McpConfig()
    if args.mcp_config_file:
        mcp_config = load_mcp_config(args.mcp_config_file)
    for spec in args.mcp:
        name, server = parse_inline_mcp(spec)
        mcp_config.mcpServers[name] = server

    run_chat(
        model=args.model,
        system_prompt=args.system_prompt,
        api_key=args.api_key,
        container=args.container,
        memory=args.memory,
        cpus=args.cpus,
        disk=args.disk,
        mcp_config=mcp_config if mcp_config.mcpServers else None,
        resume_session=args.session,
        resume_conversation=args.conversation,
        max_budget=args.max_budget,
    )


if __name__ == "__main__":
    main()
