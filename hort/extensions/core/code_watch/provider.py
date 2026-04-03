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


class CodeWatch(PluginBase, MCPMixin):
    """Code session monitor — observes and interacts with tmux sessions."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Code-watch activated")

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="list_sessions",
                description=(
                    "List all active code sessions (tmux sessions with hort_ prefix). "
                    "Returns session name, status, current command, and whether it's busy."
                ),
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="read_output",
                description=(
                    "Read the recent terminal output of a code session. "
                    "Returns the last N lines of the session's screen + scrollback."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name (without hort_ prefix)",
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of scrollback lines to capture (default: 100)",
                            "default": 100,
                        },
                    },
                    "required": ["session"],
                },
            ),
            MCPToolDef(
                name="is_busy",
                description=(
                    "Check if a code session has a process running (True) "
                    "or is idle at a shell prompt (False)."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name (without hort_ prefix)",
                        },
                    },
                    "required": ["session"],
                },
            ),
            MCPToolDef(
                name="send_text",
                description=(
                    "Send text input to a code session. By default appends Enter "
                    "to execute as a command. Set enter=false to type without executing."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name (without hort_ prefix)",
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to send",
                        },
                        "enter": {
                            "type": "boolean",
                            "description": "Append Enter key (default: true)",
                            "default": True,
                        },
                    },
                    "required": ["session", "text"],
                },
            ),
            MCPToolDef(
                name="create_session",
                description=(
                    "Create a new tmux code session. Optionally specify a command "
                    "to run (default: user's shell) and working directory."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Session name (will be prefixed with hort_)",
                        },
                        "command": {
                            "type": "string",
                            "description": "Command to run (default: shell)",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Working directory",
                        },
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
                        "session": {
                            "type": "string",
                            "description": "Session name (without hort_ prefix)",
                        },
                    },
                    "required": ["session"],
                },
            ),
            MCPToolDef(
                name="attach_web_terminal",
                description=(
                    "Bridge a tmux session to a browser web terminal. Returns "
                    "a terminal_id that can be opened in the browser at "
                    "/ws/terminal/{terminal_id}."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name (without hort_ prefix)",
                        },
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
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": "No active code sessions. Create one with `hort watch <name>`.",
                }])
            lines = []
            for s in sessions:
                status = "busy" if tmux_is_busy(s.short_name) else "idle"
                attached = " (attached)" if s.attached else ""
                lines.append(
                    f"  {s.short_name}: {status}{attached}"
                    f" — running: {s.current_command}"
                )
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Active sessions ({len(sessions)}):\n" + "\n".join(lines),
            }])

        if tool_name == "read_output":
            session = arguments["session"]
            lines = arguments.get("lines", 100)
            output = tmux_read(session, lines=lines)
            if output is None:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Session '{session}' not found."}],
                    is_error=True,
                )
            # Strip trailing empty lines
            text = output.rstrip("\n") + "\n"
            return MCPToolResult(content=[{"type": "text", "text": text}])

        if tool_name == "is_busy":
            session = arguments["session"]
            busy = tmux_is_busy(session)
            if busy is None:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Session '{session}' not found."}],
                    is_error=True,
                )
            status = "busy (process running)" if busy else "idle (at shell prompt)"
            return MCPToolResult(content=[{
                "type": "text", "text": f"Session '{session}': {status}",
            }])

        if tool_name == "send_text":
            session = arguments["session"]
            text = arguments["text"]
            enter = arguments.get("enter", True)
            if not tmux_exists(session):
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Session '{session}' not found."}],
                    is_error=True,
                )
            ok = tmux_send(session, text, enter=enter)
            if not ok:
                return MCPToolResult(
                    content=[{"type": "text", "text": "Failed to send text."}],
                    is_error=True,
                )
            action = f"Sent to '{session}'" + (" (with Enter)" if enter else " (no Enter)")
            return MCPToolResult(content=[{"type": "text", "text": action}])

        if tool_name == "create_session":
            name = arguments["name"]
            command = arguments.get("command")
            cwd = arguments.get("cwd")
            session = tmux_create(name, command=command, cwd=cwd)
            if session is None:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Failed to create session '{name}'."}],
                    is_error=True,
                )
            return MCPToolResult(content=[{
                "type": "text",
                "text": (
                    f"Created session '{session.short_name}'.\n"
                    f"Attach in terminal: tmux attach -t {session.name}\n"
                    f"Or use: hort watch {name}"
                ),
            }])

        if tool_name == "kill_session":
            session = arguments["session"]
            if not tmux_exists(session):
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Session '{session}' not found."}],
                    is_error=True,
                )
            tmux_kill(session)
            return MCPToolResult(content=[{
                "type": "text", "text": f"Session '{session}' terminated.",
            }])

        if tool_name == "attach_web_terminal":
            session = arguments["session"]
            if not tmux_exists(session):
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Session '{session}' not found."}],
                    is_error=True,
                )
            terminal_id = await self._bridge_to_web_terminal(session)
            return MCPToolResult(content=[{
                "type": "text",
                "text": (
                    f"Web terminal ready for session '{session}'.\n"
                    f"Terminal ID: {terminal_id}\n"
                    f"Open in browser: /ws/terminal/{terminal_id}"
                ),
            }])

        return MCPToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            is_error=True,
        )

    async def _bridge_to_web_terminal(self, session_name: str) -> str:
        """Create a termd terminal session backed by tmux instead of raw PTY.

        Spawns a new terminal that runs ``tmux attach -t hort_<name>``
        so the browser shows the same tmux session the user has locally.
        Multiple browser tabs can attach to the same session.
        """
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
            # Fallback: use TerminalManager directly
            from hort.terminal import TerminalManager
            mgr = TerminalManager.get()
            ts = mgr.spawn(
                target_id="tmux",
                command=["tmux", "attach", "-t", f"{PREFIX}{session_name}"],
            )
            return ts.terminal_id
