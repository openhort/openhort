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

    name: str               # full session name (e.g., "hort_claude-api")
    short_name: str          # without prefix (e.g., "claude-api")
    attached: bool           # client currently attached
    windows: int             # number of windows
    created: str             # creation timestamp
    activity: str            # last activity timestamp
    pid: int                 # server PID
    current_command: str     # command running in active pane
    pane_pid: int            # PID of process in active pane
    allowed_plugins: tuple[str, ...] = ()  # plugins allowed to read content


# ── Preset definitions ────────────────────────────────────────────
# Maps session name → (command, allowed_plugins)
# Plugins in allowed_plugins can call read_output/send_text.
# The base system ("code-watch") always has list access but NOT
# content access unless listed here.

PRESETS: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "claude": ("claude", ("code-watch", "claude-watch")),
    "clauded": ("claude --dangerously-skip-permissions", ("code-watch", "claude-watch")),
    "shell": (None, ("code-watch",)),
}

# Fallback for unknown names: shell, only base access
DEFAULT_ALLOWED = ("code-watch",)


def list_sessions() -> list[TmuxSession]:
    """List all hort_ prefixed tmux sessions with permission metadata."""
    if not _tmux_available():
        return []

    result = _run([
        "list-sessions", "-F",
        "#{session_name}\t#{session_attached}\t#{session_windows}\t"
        "#{session_created_string}\t#{session_activity_string}\t"
        "#{pid}\t#{pane_current_command}\t#{pane_pid}",
    ])

    if result.returncode != 0:
        return []

    sessions: list[TmuxSession] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        name = parts[0]
        if not name.startswith(PREFIX):
            continue
        # Hide _web grouped sessions (browser bridges, not user sessions)
        if name.endswith("_web"):
            continue
        short = name[len(PREFIX):]
        allowed = _get_session_allowed(name)
        sessions.append(TmuxSession(
            name=name,
            short_name=short,
            attached=parts[1] == "1",
            windows=int(parts[2] or "1"),
            created=parts[3],
            activity=parts[4],
            pid=int(parts[5] or "0"),
            current_command=parts[6],
            pane_pid=int(parts[7] or "0"),
            allowed_plugins=allowed,
        ))
    return sessions


def _get_session_allowed(full_name: str) -> tuple[str, ...]:
    """Read HORT_ALLOW from the tmux session environment."""
    result = _run(["show-environment", "-t", full_name, "HORT_ALLOW"])
    if result.returncode != 0 or "=" not in result.stdout:
        # No env set — use preset defaults based on session name
        short = full_name[len(PREFIX):]
        preset = PRESETS.get(short)
        if preset:
            return preset[1]
        return DEFAULT_ALLOWED
    # Parse: "HORT_ALLOW=code-watch,claude-watch"
    val = result.stdout.strip().split("=", 1)[1]
    return tuple(p.strip() for p in val.split(",") if p.strip())


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
    allowed_plugins: tuple[str, ...] | None = None,
) -> TmuxSession | None:
    """Create a new hort_ tmux session with permission metadata.

    If ``name`` matches a preset (claude, clauded, shell), the preset's
    command and permissions are used.  Otherwise a shell is started
    with base-level permissions only.

    The ``HORT_ALLOW`` tmux environment variable records which llmings
    can read this session's content.  The dashboard shows all sessions,
    but ``read_output`` / ``send_text`` check this before returning data.

    Args:
        name: Session name (without prefix).
        command: Override command (default: from preset or shell).
        cwd: Working directory.
        cols: Terminal width.
        rows: Terminal height.
        allowed_plugins: Override allowed plugins (default: from preset).
    """
    if not _tmux_available():
        return None

    full_name = f"{PREFIX}{name}"
    if session_exists(name):
        logger.info("Session %s already exists", full_name)
        for s in list_sessions():
            if s.name == full_name:
                return s
        return None

    # Resolve preset
    preset = PRESETS.get(name)
    if command is None and preset:
        command = preset[0]
    if allowed_plugins is None:
        allowed_plugins = preset[1] if preset else DEFAULT_ALLOWED

    args = [
        "new-session", "-d",
        "-s", full_name,
        "-x", str(cols),
        "-y", str(rows),
    ]
    if cwd:
        args.extend(["-c", cwd])
    if command:
        args.append(command)

    result = _run(args)
    if result.returncode != 0:
        logger.error("Failed to create session %s: %s", full_name, result.stderr.strip())
        return None

    # Set HORT_ALLOW in the tmux session environment
    allow_str = ",".join(allowed_plugins)
    _run(["set-environment", "-t", full_name, "HORT_ALLOW", allow_str])

    logger.info("Created tmux session: %s (allow: %s)", full_name, allow_str)
    for s in list_sessions():
        if s.name == full_name:
            return s
    return None


def read_output(
    name: str,
    lines: int = DEFAULT_SCROLLBACK,
    caller_plugin: str | None = None,
) -> str | None:
    """Capture the current screen + scrollback of a session.

    If ``caller_plugin`` is set, checks ``HORT_ALLOW`` on the session.
    Only listed plugins can read content.  Pass ``None`` for system-level
    access (always permitted).

    Args:
        name: Session name (with or without prefix).
        lines: Number of scrollback lines to capture.
        caller_plugin: Llming ID requesting access (None = system).

    Returns:
        The captured text, or None if not found / access denied.
    """
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"

    if caller_plugin and not _is_plugin_allowed(full_name, caller_plugin):
        logger.warning("Plugin '%s' denied read access to '%s'", caller_plugin, name)
        return None

    result = _run([
        "capture-pane", "-t", full_name,
        "-p",
        "-S", f"-{lines}",
    ])
    if result.returncode != 0:
        return None
    return result.stdout


def send_text(
    name: str,
    text: str,
    enter: bool = True,
    caller_plugin: str | None = None,
) -> bool:
    """Send text to a tmux session.

    If ``caller_plugin`` is set, checks ``HORT_ALLOW`` on the session.

    Args:
        name: Session name (with or without prefix).
        text: Text to send.
        enter: Whether to append Enter key.
        caller_plugin: Llming ID requesting access (None = system).

    Returns:
        True if successful, False if denied or failed.
    """
    full_name = name if name.startswith(PREFIX) else f"{PREFIX}{name}"

    if caller_plugin and not _is_plugin_allowed(full_name, caller_plugin):
        logger.warning("Plugin '%s' denied send access to '%s'", caller_plugin, name)
        return False

    args = ["send-keys", "-t", full_name, text]
    if enter:
        args.append("Enter")
    result = _run(args)
    return result.returncode == 0


def _is_plugin_allowed(full_name: str, plugin_id: str) -> bool:
    """Check if a plugin is in the session's HORT_ALLOW list."""
    allowed = _get_session_allowed(full_name)
    return plugin_id in allowed


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
