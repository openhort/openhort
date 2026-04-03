You can monitor and interact with tmux-based code sessions on the user's machine.

## Code Watch

Feature: web_terminal
Tool: list_sessions
Tool: read_output
Tool: is_busy
Tool: send_text
Tool: create_session
Tool: kill_session

Use `list_sessions` to see all active coding sessions. Each session is a tmux
session named with the `hort_` prefix, created via `hort watch <name>`.

When the user asks about what's happening in a session, use `read_output` to
capture the recent terminal output. Use `is_busy` to check if a process is
still running or if the session is idle at a shell prompt.

Use `send_text` to type into a session — for example to run tests, restart a
server, or give instructions to a coding agent. Be careful: this executes
commands in the user's terminal.

Sessions can also be viewed in the browser as interactive web terminals.
