"""Tmux session management for code-watch.

Discovers, creates, reads, and writes tmux sessions with the ``hort:``
prefix.  Any tmux session named ``hort:<name>`` is considered an
openhort-managed code session.

Users create sessions via ``hort watch <name>`` (which runs
``tmux new-session -s hort:<name>``).  OpenHORT discovers them
automatically and exposes them as MCP tools.

Architecture::

    User's terminal          OpenHORT
    ┌────────────┐          ┌──────────────────┐
    │ tmux session│          │ code-watch llming │
    │ hort:claude │◄────────►│ read_output()     │
    │             │  tmux    │ send_text()       │
    │ $ claude    │  cmds    │ is_busy()         │
    └────────────┘          └──────────────────┘

No PTY ownership — just tmux commands.  The user owns the session;
openhort observes and interacts.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("hort.tmux")

PREFIX = "hort_"
DEFAULT_SCROLLBACK = 200


def _tmux_available() -> bool:
    """Check if tmux is installed."""
    return shutil.which("tmux") is not None


def _run(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    """Run a tmux command and return the result."""
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@dataclass(frozen=True)
class TmuxSession:
    """Info about a discovered tmux session."""

    name: str               # full session name (e.g., "hort:claude-api")
    short_name: str          # without prefix (e.g., "claude-api")
    attached: bool           # client currently attached
    windows: int             # number of windows
    created: str             # creation timestamp
    activity: str            # last activity timestamp
    pid: int                 # server PID
    current_command: str     # command running in active pane
    pane_pid: int            # PID of process in active pane


def list_sessions() -> list[TmuxSession]:
    """List all hort: prefixed tmux sessions."""
    if not _tmux_available():
        return []

    result = _run([
        "list-sessions", "-F",
        "#{session_name}\t#{session_attached}\t#{session_windows}\t"
        "#{session_created_string}\t#{session_activity_string}\t"
        "#{pid}\t#{pane_current_command}\t#{pane_pid}",
    ])

    if result.returncode != 0:
        # No tmux server running or no sessions
        return []

    sessions: list[TmuxSession] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        name = parts[0]
        if not name.startswith(PREFIX):
            continue
        sessions.append(TmuxSession(
            name=name,
            short_name=name[len(PREFIX):],
            attached=parts[1] == "1",
            windows=int(parts[2] or "1"),
            created=parts[3],
            activity=parts[4],
            pid=int(parts[5] or "0"),
            current_command=parts[6],
            pane_pid=int(parts[7] or "0"),
        ))
    return sessions


def session_exists(name: str) -> bool:
    """Check if a hort: session exists."""
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"
    result = _run(["has-session", "-t", full_name])
    return result.returncode == 0


def create_session(
    name: str,
    command: str | None = None,
    cwd: str | None = None,
    cols: int = 200,
    rows: int = 50,
) -> TmuxSession | None:
    """Create a new hort: tmux session.

    Args:
        name: Session name (without prefix). Will be created as ``hort:<name>``.
        command: Optional command to run (default: user's shell).
        cwd: Working directory.
        cols: Terminal width.
        rows: Terminal height.

    Returns:
        The created TmuxSession, or None if creation failed.
    """
    if not _tmux_available():
        return None

    full_name = f"{PREFIX}{name}"
    if session_exists(name):
        logger.info("Session %s already exists", full_name)
        # Return existing session info
        for s in list_sessions():
            if s.name == full_name:
                return s
        return None

    args = [
        "new-session", "-d",           # detached
        "-s", full_name,               # session name
        "-x", str(cols),               # width
        "-y", str(rows),               # height
    ]
    if cwd:
        args.extend(["-c", cwd])
    if command:
        args.append(command)

    result = _run(args)
    if result.returncode != 0:
        logger.error("Failed to create session %s: %s", full_name, result.stderr.strip())
        return None

    logger.info("Created tmux session: %s", full_name)
    # Fetch the session info
    for s in list_sessions():
        if s.name == full_name:
            return s
    return None


def read_output(
    name: str,
    lines: int = DEFAULT_SCROLLBACK,
) -> str | None:
    """Capture the current screen + scrollback of a session.

    Args:
        name: Session name (with or without prefix).
        lines: Number of scrollback lines to capture.

    Returns:
        The captured text, or None if the session doesn't exist.
    """
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"
    result = _run([
        "capture-pane", "-t", full_name,
        "-p",                          # print to stdout
        "-S", f"-{lines}",             # scrollback lines
    ])
    if result.returncode != 0:
        return None
    return result.stdout


def send_text(
    name: str,
    text: str,
    enter: bool = True,
) -> bool:
    """Send text to a tmux session.

    Args:
        name: Session name (with or without prefix).
        text: Text to send.
        enter: Whether to append Enter key.

    Returns:
        True if successful.
    """
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"
    args = ["send-keys", "-t", full_name, text]
    if enter:
        args.append("Enter")
    result = _run(args)
    return result.returncode == 0


def is_busy(name: str) -> bool | None:
    """Check if a process is running in the session (not at shell prompt).

    Returns True if busy, False if at shell prompt, None if session
    doesn't exist.

    Heuristic: if the current command is a shell (bash, zsh, fish, sh),
    the session is idle.  Otherwise it's busy.
    """
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"
    if not session_exists(full_name):
        return None
    result = _run([
        "display-message", "-t", full_name,
        "-p", "#{pane_current_command}",
    ])
    if result.returncode != 0:
        return None
    cmd = result.stdout.strip()
    if not cmd:
        return None
    shells = {"bash", "zsh", "fish", "sh", "dash", "tcsh", "csh", "-bash", "-zsh", "login"}
    return cmd not in shells


def get_pane_pid(name: str) -> int | None:
    """Get the PID of the process running in the session's active pane."""
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"
    result = _run([
        "display-message", "-t", full_name,
        "-p", "#{pane_pid}",
    ])
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def kill_session(name: str) -> bool:
    """Kill a tmux session.

    Args:
        name: Session name (with or without prefix).

    Returns:
        True if the session was killed.
    """
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"
    result = _run(["kill-session", "-t", full_name])
    return result.returncode == 0


def resize_session(name: str, cols: int, rows: int) -> bool:
    """Resize a tmux session's window."""
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"
    result = _run([
        "resize-window", "-t", full_name,
        "-x", str(cols), "-y", str(rows),
    ])
    return result.returncode == 0
