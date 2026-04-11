"""CLI entry point for ``hort watch <name>``.

Creates or attaches to a tmux session with the ``hort_`` prefix.
If the session exists, attaches. If not, creates it with the
appropriate command and attaches.

Named presets run specific commands automatically::

    hort watch claude                 # runs: claude
    hort watch clauded                # runs: claude --dangerously-skip-permissions
    hort watch shell                  # just a shell
    hort watch shell /my/project      # shell in a directory
    hort watch my-project             # unknown name → shell
    hort watch --list                 # list active sessions
"""

from __future__ import annotations

import os
import sys

def _get_preset_command(name: str) -> str | None:
    """Get the command for a preset name, or None for shell."""
    from hort.tmux import PRESETS
    preset = PRESETS.get(name)
    return preset[0] if preset else None


def main(args: list[str] | None = None) -> None:
    """CLI entry point."""
    args = args if args is not None else sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        _print_help()
        return

    if args[0] in ("-l", "--list"):
        _list_sessions()
        return

    name = args[0]
    cwd = None
    if len(args) > 1:
        cwd = args[1]

    _watch(name, cwd=cwd)


def _print_help() -> None:
    print("Usage: hort watch <name> [cwd]")
    print()
    print("Create or attach to a tmux code session.")
    print("Sessions are named hort_<name> and discoverable by openhort.")
    print()
    print("Presets:")
    print("  claude          Start Claude Code")
    print("  clauded         Start Claude Code (dangerous mode)")
    print("  shell           Just a shell")
    print("  <anything>      Shell (no preset)")
    print()
    print("Options:")
    print("  -l, --list      List active code sessions")
    print("  -h, --help      Show this help")
    print()
    print("Examples:")
    print("  hort watch claude              # Claude Code session")
    print("  hort watch clauded             # Claude Code (dangerous)")
    print("  hort watch shell /my/project   # shell in directory")
    print("  hort watch my-api              # shell session")
    print("  hort watch --list              # show all sessions")


def _watch(name: str, cwd: str | None = None) -> None:
    """Create or attach to a hort_ tmux session."""
    from hort.tmux import PREFIX, session_exists, create_session

    if session_exists(name):
        print(f"Attaching to existing session: {PREFIX}{name}")
    else:
        # create_session resolves presets (command + permissions) internally
        session = create_session(name, cwd=cwd or os.getcwd())
        if session is None:
            print(f"Failed to create session {PREFIX}{name}", file=sys.stderr)
            sys.exit(1)
        from hort.tmux import PRESETS as _P
        what = (_P.get(name) or (None,))[0] or "shell"
        print(f"Created session: {PREFIX}{name} ({what})")

    # Attach interactively (replaces this process)
    os.execvp("tmux", ["tmux", "attach", "-t", f"{PREFIX}{name}"])


def _list_sessions() -> None:
    """List all hort_ tmux sessions."""
    from hort.tmux import list_sessions, is_busy

    sessions = list_sessions()
    if not sessions:
        print("No active code sessions.")
        print("Create one: hort watch <name>")
        return

    print(f"Active sessions ({len(sessions)}):")
    for s in sessions:
        busy = is_busy(s.short_name)
        status = "busy" if busy else "idle"
        attached = " (attached)" if s.attached else ""
        print(f"  {s.short_name:20s} {status:6s}{attached}  [{s.current_command}]")


if __name__ == "__main__":
    main()
