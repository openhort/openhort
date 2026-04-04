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


def _detect_session_state(session_name: str, current_command: str) -> dict[str, Any]:
    """Detect full Claude Code state from terminal output.

    Returns a dict with state, mode, detail, border_color, idle_seconds.
    """
    from .detect import ClaudeState, detect_state

    shells = {"bash", "zsh", "fish", "sh", "-bash", "-zsh", "login"}

    # Not a Claude session — simple busy/idle
    if "claude" not in session_name and current_command not in ("claude", "2.1.91"):
        if current_command in shells:
            return {"state": "idle", "mode": "normal", "detail": "", "border_color": "", "idle_seconds": 0}
        return {"state": "busy", "mode": "normal", "detail": current_command, "border_color": "#eab308", "idle_seconds": 0}

    # Claude session — read VISIBLE pane (not scrollback) for status bar detection
    try:
        from hort.tmux import read_visible
        output = read_visible(session_name)
        if not output:
            return {"state": "busy", "mode": "normal", "detail": "", "border_color": "#8b5cf6", "idle_seconds": 0}

        # Get or create previous state for since tracking
        prev = _session_states.get(session_name)
        cs = detect_state(output, session_name=session_name, previous_state=prev)
        _session_states[session_name] = cs

        return {
            "state": cs.state,
            "mode": cs.mode,
            "detail": cs.detail,
            "border_color": _state_border_color(cs),
            "idle_seconds": round(cs.idle_seconds, 1),
            "needs_input": cs.needs_input,
            "last_output": cs.last_output,
        }
    except Exception:
        return {"state": "busy", "mode": "normal", "detail": "", "border_color": "#8b5cf6", "idle_seconds": 0}


# Track previous state per session for `since` continuity
_session_states: dict[str, Any] = {}


def _state_border_color(cs: Any) -> str:
    """Map Claude state + mode to a border color."""
    # Mode takes priority for border color
    mode_colors = {
        "dangerous": "#ef4444",     # red
        "plan": "#3b82f6",          # blue
        "accept_edits": "#f59e0b",  # amber
    }
    if cs.mode in mode_colors:
        return mode_colors[cs.mode]

    # State-based colors
    state_colors = {
        "thinking": "#a78bfa",      # light purple (working)
        "responding": "#8b5cf6",    # purple (active)
        "tool_running": "#6366f1",  # indigo (executing)
        "selecting": "#f59e0b",     # amber (needs input)
        "permission": "#ef4444",    # red (needs approval)
        "idle": "",                 # no border
        "busy": "#eab308",          # yellow
    }
    return state_colors.get(cs.state, "")


# ── Extension class ───────────────────────────────────────────────


class CodeWatch(PluginBase, MCPMixin):
    """Code session monitor — observes and interacts with tmux sessions."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Code-watch activated")

    def get_status(self) -> dict[str, Any]:
        """Return session data for the dashboard with full state detection."""
        from hort.tmux import list_sessions

        sessions = []
        for s in list_sessions():
            info = _detect_session_state(s.short_name, s.current_command)
            sessions.append({
                "name": s.short_name,
                "command": s.current_command,
                "attached": s.attached,
                **info,
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
