# Code Watch Extension

Developer reference for the `openhort/code-watch` llming — tmux session management, Claude state detection, and the terminal bridge.

## Module Structure

```
hort/tmux.py                              Core tmux operations
hort/extensions/core/code_watch/
    extension.json                        Manifest (MCP, groups, risk level)
    provider.py                           MCP tools + get_status() + state detector bridge
    detect.py                             Claude Code state machine
    cli.py                                hort watch CLI entry point
    SOUL.md                               LLM instructions
```

## tmux.py — Session Management

All tmux operations go through `hort/tmux.py`. Sessions use the `hort_` prefix for discovery.

### Key Functions

```python
from hort.tmux import (
    create_session,     # Create hort_<name> with presets + HORT_ALLOW
    list_sessions,      # Discover all hort_* sessions (excludes _web bridges)
    read_output,        # Scrollback capture (permission-gated by caller_plugin)
    read_visible,       # Visible pane only (for state detection)
    send_text,          # Send keystrokes (permission-gated)
    is_busy,            # Shell prompt vs running process
    kill_session,       # Kill session
    session_exists,     # Check existence
    get_pane_pid,       # PID of process in active pane
)
```

### Presets

Defined in `hort/tmux.py`:

```python
PRESETS = {
    "claude":  ("claude", ("code-watch", "claude-watch")),
    "clauded": ("claude --dangerously-skip-permissions", ("code-watch", "claude-watch")),
    "shell":   (None, ("code-watch",)),
}
```

Each preset defines `(command, allowed_plugins)`. Unknown names get `(None, ("code-watch",))` — a shell with base access only.

### Permission Gating (HORT_ALLOW)

When a session is created, `HORT_ALLOW` is set in the tmux environment:

```bash
tmux set-environment -t hort_claude HORT_ALLOW "code-watch,claude-watch"
```

`read_output()` and `send_text()` accept a `caller_plugin` parameter. If provided, the session's `HORT_ALLOW` is checked before returning data:

```python
# System-level access (always permitted)
output = read_output("claude")

# Plugin-level access (checked against HORT_ALLOW)
output = read_output("claude", caller_plugin="claude-watch")   # allowed
output = read_output("claude", caller_plugin="evil-plugin")    # returns None
```

### read_visible vs read_output

| Function | tmux command | Returns | Use case |
|----------|------------|---------|----------|
| `read_output(name, lines=200)` | `capture-pane -p -S -200` | Scrollback history | Reading terminal output |
| `read_visible(name)` | `capture-pane -p` | Visible pane only | State detection (needs status bar) |

`read_visible` is critical for state detection because `esc to interrupt` appears in the status bar at the bottom of the visible pane, which scrollback capture may miss.

## detect.py — Claude State Machine

Parses the visible terminal pane to determine Claude Code's current state.

### States

| State | Detection signal | Card indicator |
|-------|-----------------|----------------|
| `idle` | `❯` prompt, stable screen, no `esc to interrupt` | Animated Zzz |
| `thinking` | `esc to interrupt` in status bar, or `✻` spinner | Spinning ⚡ |
| `responding` | Screen content changing between polls | Spinning ⚡ |
| `tool_running` | `!` prefix in output | Spinning ⚡ |
| `selecting` | Numbered list (`1.` `2.` `3.`) | Amber border |
| `permission` | Allow/Deny prompt | Red border |

### Modes

| Mode | Detection signal | Border color |
|------|-----------------|-------------|
| `normal` | No mode indicator | None |
| `dangerous` | `bypass permissions on` | `#ef4444` (red) |
| `plan` | `plan mode on` | `#3b82f6` (blue) |
| `accept_edits` | `accept edits on` | `#f59e0b` (amber) |

### Content Change Detection

Claude streams responses without explicit indicators — the screen just changes. The detector hashes screen content between polls:

```python
content_hash = hashlib.md5(output.encode()).hexdigest()[:12]
content_changed = previous_hash != "" and previous_hash != content_hash
```

If content changed AND the `❯` prompt is visible, Claude is still streaming (state = `responding`). If content is stable AND prompt is visible, Claude is idle.

### State Continuity (`since`)

Each state tracks when it started. If the state is the same as the previous poll, `since` is preserved:

```python
state.idle_seconds  # 0 if not idle, else time.time() - since
state.is_idle       # True if state == "idle"
state.is_working    # True if thinking/responding/tool_running
state.needs_input   # True if idle/selecting/permission
```

### last_output

The detector extracts the last 3 meaningful lines (skipping separators, mode indicators, prompts) for the dashboard's live preview.

## provider.py — MCP Tools & Dashboard

### get_status()

Called by the dashboard polling cycle. Returns per-session state with border colors:

```python
{
    "sessions": [{
        "name": "clauded",
        "command": "2.1.91",
        "attached": true,
        "state": "idle",
        "mode": "dangerous",
        "border_color": "#ef4444",
        "idle_seconds": 354.6,
        "needs_input": true,
        "last_output": "The end.\n⎿ Interrupted · What should Claude do instead?"
    }],
    "count": 1
}
```

### Controller Integration

The controller (`hort/controller.py`) runs `_detect_session_state()` for each tmux session in the `terminal_list` response, injecting `border_color`, `claude_state`, `mode`, `idle_seconds`, and `last_output` into the terminal data sent to the dashboard.

### Web Terminal Bridge

Clicking a tmux card in the dashboard creates a grouped tmux session:

```bash
tmux new-session -t hort_clauded -s hort_clauded_web
```

Grouped sessions share windows but have independent sizes — the browser and iTerm can be attached simultaneously without size conflicts. The `_web` sessions are hidden from the dashboard grid.

## Testing

```bash
# Unit tests for state detection (31 tests, no tmux needed)
poetry run pytest tests/test_claude_detect.py -v

# E2E tests with real tmux sessions (29 tests, requires tmux)
poetry run pytest tests/test_tmux.py -v
```

Test coverage:
- All 6 states + 4 modes
- Content change detection
- `since` continuity
- Real-world output samples
- MCP tool execution
- Session lifecycle (create, list, read, write, kill)
- Permission gating
