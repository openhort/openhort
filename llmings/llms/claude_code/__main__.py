"""Entry point: poetry run python -m llmings.llms.claude_code"""

from __future__ import annotations

import sys

from .chat import run_chat
from hort.sandbox.mcp import McpConfig, load_mcp_config, parse_inline_mcp


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


def _destroy_session(session_id: str) -> None:
    from hort.sandbox import SessionManager
    mgr = SessionManager()
    if mgr.destroy(session_id):
        print(f"Session {session_id} destroyed.")
    else:
        print(f"Session {session_id} not found.")
        sys.exit(1)


def _cleanup() -> None:
    from hort.llm import ConversationStore
    from hort.sandbox import SessionManager
    from hort.sandbox.reaper import reap
    mgr = SessionManager()
    destroyed = reap(mgr, max_sessions=20, max_bytes=5 * 1024**3)
    conv_destroyed = ConversationStore().cleanup_expired()
    total = len(destroyed) + len(conv_destroyed)
    if total:
        print(f"Cleaned up {total} item(s).")
    else:
        print("Nothing to clean up.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Chat with Claude Code",
    )
    parser.add_argument("--model", "-m", help="Model (e.g. sonnet, opus, haiku)")
    parser.add_argument("--system", "-s", dest="system_prompt", help="System prompt")
    parser.add_argument("--container", "-c", action="store_true", help="Run in Docker sandbox")
    parser.add_argument("--memory", help="Container memory limit (e.g. 512m, 2g)")
    parser.add_argument("--cpus", type=float, help="Container CPU limit")
    parser.add_argument("--disk", help="Container disk limit (e.g. 1g)")
    parser.add_argument("--mcp", action="append", default=[],
                        help="Add MCP: name=command [args...]")
    parser.add_argument("--mcp-config", dest="mcp_config_file",
                        help="Path to MCP config JSON file")
    parser.add_argument("--max-budget", type=float,
                        help="Maximum USD to spend (e.g. 2.00)")
    parser.add_argument("--session", help="Resume an existing sandbox session")
    parser.add_argument("--list-sessions", action="store_true",
                        help="List all sandbox sessions")
    parser.add_argument("--destroy-session", metavar="ID",
                        help="Destroy a sandbox session")
    parser.add_argument("--cleanup", action="store_true",
                        help="Clean up expired sessions + conversations")
    args = parser.parse_args()

    if args.list_sessions:
        _list_sessions()
        return
    if args.destroy_session:
        _destroy_session(args.destroy_session)
        return
    if args.cleanup:
        _cleanup()
        return

    if (args.memory or args.cpus or args.disk) and not args.container:
        parser.error("--memory, --cpus, and --disk require --container")
    if args.session and not args.container:
        parser.error("--session requires --container")

    mcp_config = McpConfig()
    if args.mcp_config_file:
        mcp_config = load_mcp_config(args.mcp_config_file)
    for spec in args.mcp:
        name, server = parse_inline_mcp(spec)
        mcp_config.mcpServers[name] = server

    run_chat(
        model=args.model, system_prompt=args.system_prompt,
        container=args.container, memory=args.memory,
        cpus=args.cpus, disk=args.disk,
        mcp_config=mcp_config if mcp_config.mcpServers else None,
        resume_session=args.session,
        max_budget=args.max_budget,
    )


if __name__ == "__main__":
    main()
