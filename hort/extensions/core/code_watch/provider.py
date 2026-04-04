"""Code-watch llming — monitor and interact with tmux code sessions.

Provides MCP tools for listing, reading, writing, and managing
tmux-based code sessions.  Sessions are identified by the ``hort_``
prefix in their tmux session name.

Also supports bridging tmux sessions to browser web terminals via
the ``attach_web_terminal`` tool, which creates a termd-compatible
terminal session backed by the tmux session instead of a raw PTY.
"""

from __future__ import annotations

from typing import Any

from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase


# ── Helpers (module-level) ────────────────────────────────────────


def _detect_claude_mode(session_name: str, current_command: str) -> str:
    """Detect what mode a Claude Code session is in.

    Returns one of: "dangerous", "plan", "claude", "busy", "idle".
    """
    shells = {"bash", "zsh", "fish", "sh", "-bash", "-zsh", "login"}

    if "clauded" in session_name:
        return "idle" if current_command in shells else "dangerous"

    if "claude" in session_name or current_command == "claude":
        if current_command in shells:
            return "idle"
        try:
            from hort.tmux import read_output
            output = read_output(session_name, lines=5)
            if output and "plan mode" in output.lower():
                return "plan"
        except Exception:
            pass
        return "claude"

    return "idle" if current_command in shells else "busy"


def _mode_border_color(mode: str, busy: bool | None) -> str:
    """Map a session mode to a CSS border color."""
    return {
        "dangerous": "#ef4444",
        "plan": "#3b82f6",
        "claude": "#8b5cf6",
        "busy": "#eab308",
        "idle": "",
    }.get(mode, "")


# ── Extension class ───────────────────────────────────────────────


class CodeWatch(PluginBase, MCPMixin):
    """Code session monitor — observes and interacts with tmux sessions."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Code-watch activated")

    def get_status(self) -> dict[str, Any]:
        """Return session data for the dashboard with border colors."""
        from hort.tmux import list_sessions, is_busy

        sessions = []
        for s in list_sessions():
            busy = is_busy(s.short_name)
            mode = _detect_claude_mode(s.short_name, s.current_command)
            border = _mode_border_color(mode, busy)
            sessions.append({
                "name": s.short_name,
                "busy": busy,
                "command": s.current_command,
                "attached": s.attached,
                "mode": mode,
                "border_color": border,
            })
        return {"sessions": sessions, "count": len(sessions)}

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="list_sessions",
                description="List all active code sessions (tmux sessions with hort_ prefix).",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="read_output",
                description="Read the recent terminal output of a code session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {"type": "string", "description": "Session name (without hort_ prefix)"},
                        "lines": {"type": "integer", "description": "Scrollback lines (default: 100)", "default": 100},
                    },
                    "required": ["session"],
                },
            ),
            MCPToolDef(
                name="is_busy",
                description="Check if a code session has a running process (True) or is idle (False).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {"type": "string", "description": "Session name (without hort_ prefix)"},
                    },
                    "required": ["session"],
                },
            ),
            MCPToolDef(
                name="send_text",
                description="Send text input to a code session. Appends Enter by default.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {"type": "string", "description": "Session name"},
                        "text": {"type": "string", "description": "Text to send"},
                        "enter": {"type": "boolean", "description": "Append Enter (default: true)", "default": True},
                    },
                    "required": ["session", "text"],
                },
            ),
            MCPToolDef(
                name="create_session",
                description="Create a new tmux code session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Session name (prefixed with hort_)"},
                        "command": {"type": "string", "description": "Command to run (default: shell)"},
                        "cwd": {"type": "string", "description": "Working directory"},
                    },
                    "required": ["name"],
                },
            ),
            MCPToolDef(
                name="kill_session",
                description="Kill (terminate) a code session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {"type": "string", "description": "Session name"},
                    },
                    "required": ["session"],
                },
            ),
            MCPToolDef(
                name="attach_web_terminal",
                description="Bridge a tmux session to a browser web terminal.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {"type": "string", "description": "Session name"},
                    },
                    "required": ["session"],
                },
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any],
    ) -> MCPToolResult:
        from hort.tmux import (
            create_session as tmux_create,
            is_busy as tmux_is_busy,
            kill_session as tmux_kill,
            list_sessions as tmux_list,
            read_output as tmux_read,
            send_text as tmux_send,
            session_exists as tmux_exists,
        )

        if tool_name == "list_sessions":
            sessions = tmux_list()
            if not sessions:
                return MCPToolResult(content=[{"type": "text", "text": "No active code sessions."}])
            lines = []
            for s in sessions:
                status = "busy" if tmux_is_busy(s.short_name) else "idle"
                attached = " (attached)" if s.attached else ""
                lines.append(f"  {s.short_name}: {status}{attached} — {s.current_command}")
            return MCPToolResult(content=[{"type": "text", "text": f"Active sessions ({len(sessions)}):\n" + "\n".join(lines)}])

        if tool_name == "read_output":
            session = arguments["session"]
            n = arguments.get("lines", 100)
            output = tmux_read(session, lines=n, caller_plugin="code-watch")
            if output is None:
                return MCPToolResult(content=[{"type": "text", "text": f"Session '{session}' not found or access denied."}], is_error=True)
            return MCPToolResult(content=[{"type": "text", "text": output.rstrip("\n") + "\n"}])

        if tool_name == "is_busy":
            session = arguments["session"]
            busy = tmux_is_busy(session)
            if busy is None:
                return MCPToolResult(content=[{"type": "text", "text": f"Session '{session}' not found."}], is_error=True)
            status = "busy (process running)" if busy else "idle (at shell prompt)"
            return MCPToolResult(content=[{"type": "text", "text": f"Session '{session}': {status}"}])

        if tool_name == "send_text":
            session = arguments["session"]
            text = arguments["text"]
            enter = arguments.get("enter", True)
            if not tmux_exists(session):
                return MCPToolResult(content=[{"type": "text", "text": f"Session '{session}' not found."}], is_error=True)
            ok = tmux_send(session, text, enter=enter, caller_plugin="code-watch")
            if not ok:
                return MCPToolResult(content=[{"type": "text", "text": "Failed to send (access denied or session error)."}], is_error=True)
            return MCPToolResult(content=[{"type": "text", "text": f"Sent to '{session}'"}])

        if tool_name == "create_session":
            name = arguments["name"]
            session = tmux_create(name, command=arguments.get("command"), cwd=arguments.get("cwd"))
            if session is None:
                return MCPToolResult(content=[{"type": "text", "text": f"Failed to create '{name}'."}], is_error=True)
            return MCPToolResult(content=[{"type": "text", "text": f"Created session '{session.short_name}'."}])

        if tool_name == "kill_session":
            session = arguments["session"]
            if not tmux_exists(session):
                return MCPToolResult(content=[{"type": "text", "text": f"Session '{session}' not found."}], is_error=True)
            tmux_kill(session)
            return MCPToolResult(content=[{"type": "text", "text": f"Session '{session}' terminated."}])

        if tool_name == "attach_web_terminal":
            session = arguments["session"]
            if not tmux_exists(session):
                return MCPToolResult(content=[{"type": "text", "text": f"Session '{session}' not found."}], is_error=True)
            terminal_id = await self._bridge_to_web_terminal(session)
            return MCPToolResult(content=[{"type": "text", "text": f"Web terminal ready: {terminal_id}"}])

        return MCPToolResult(content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}], is_error=True)

    async def _bridge_to_web_terminal(self, session_name: str) -> str:
        """Bridge a tmux session to a browser web terminal."""
        from hort.tmux import PREFIX
        try:
            from hort.termd_client import ensure_daemon, spawn_terminal
            await ensure_daemon()
            result = await spawn_terminal(
                target_id="tmux",
                command=["tmux", "attach", "-t", f"{PREFIX}{session_name}"],
            )
            return result.get("terminal_id", "")
        except Exception as exc:
            self.log.error("Failed to bridge tmux session: %s", exc)
            from hort.terminal import TerminalManager
            mgr = TerminalManager.get()
            ts = mgr.spawn(target_id="tmux", command=["tmux", "attach", "-t", f"{PREFIX}{session_name}"])
            return ts.terminal_id
