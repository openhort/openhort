"""Claude Code state detection from terminal output.

Parses the bottom of a tmux pane to determine what Claude Code is
doing right now.  Detection is based on visible indicators, not
internal API — it reads what the user sees.

States:
    idle          ❯ prompt visible, screen stable — waiting for user input
    thinking      ✻ / Harmonizing... / spinner visible — model is processing
    tool_running  ! tool output appearing — executing a tool (Bash, Read, etc.)
    responding    ⏺ text streaming — Claude is writing a response
    plan_mode     ⏸ plan mode on — in plan mode, may show numbered options
    selecting     numbered list (1. 2. 3.) visible — waiting for user selection
    permission    permission prompt visible — waiting for user to approve/deny
    busy          screen content changing — something is happening

Each state includes:
    since         timestamp when this state was first detected
    detail        extra info (e.g., which tool, what mode indicator)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


@dataclass
class ClaudeState:
    """Detected state of a Claude Code session."""

    state: str                      # idle, thinking, tool_running, responding, selecting, plan_mode, permission, busy
    detail: str = ""                # e.g., tool name, mode indicator text
    mode: str = "normal"            # normal, dangerous, plan, accept_edits
    since: float = 0.0              # timestamp when this state was first detected
    session_name: str = ""
    _content_hash: str = ""         # hash of screen content for change detection
    last_output: str = ""           # last few lines of meaningful content

    @property
    def is_idle(self) -> bool:
        return self.state == "idle"

    @property
    def is_working(self) -> bool:
        return self.state in ("thinking", "tool_running", "responding", "busy")

    @property
    def needs_input(self) -> bool:
        return self.state in ("idle", "selecting", "permission")

    @property
    def idle_seconds(self) -> float:
        if not self.is_idle or self.since == 0:
            return 0.0
        return time.time() - self.since


# ── Pattern constants ─────────────────────────────────────────────

# Mode indicators (bottom status bar)
_MODE_PATTERNS = {
    "bypass permissions on": "dangerous",
    "plan mode on": "plan",
    "accept edits on": "accept_edits",
}

# State indicators
_PROMPT_RE = re.compile(r"^❯[\s\xa0]*$")                # idle prompt (empty input line, may have nbsp)
_PROMPT_INPUT_RE = re.compile(r"^❯[\s\xa0]+\S")        # prompt with user typing
_THINKING_RE = re.compile(r"✻\s*\w+|esc to interrupt")    # "✻ Waddling..." or "esc to interrupt"
_TOOL_RE = re.compile(r"^!\s+\S")                      # tool execution (! command)
_RESPONSE_RE = re.compile(r"^⏺\s+\S")                  # Claude responding
_SELECTION_RE = re.compile(r"^\s*\d+\.\s+\S")           # numbered selection (1. foo, 2. bar)
_PERMISSION_RE = re.compile(r"Allow|Deny|approve|reject|permission", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^[─━]{4,}$")               # horizontal separator line


def detect_state(
    output: str,
    session_name: str = "",
    previous_state: ClaudeState | None = None,
) -> ClaudeState:
    """Detect Claude Code's current state from terminal output.

    Uses three signals:
    1. Status bar indicators (``esc to interrupt``, mode text)
    2. Content markers (``✻``, ``⏺``, ``!``, ``❯``)
    3. Screen content changes — if the screen changed significantly
       since last poll, Claude is actively working (streaming response)

    Args:
        output: Terminal output (from ``tmux capture-pane``).
        session_name: Session name for context.
        previous_state: Previous state for ``since`` tracking.

    Returns:
        Detected ClaudeState.
    """
    lines = output.splitlines() if output else []

    # Strip trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return ClaudeState(state="idle", session_name=session_name, since=time.time())

    # ── Extract last meaningful output ────────────────────────
    # Skip prompts, separators, mode indicators — keep actual content
    _content_lines = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if _SEPARATOR_RE.match(s):
            continue
        if any(p in s for p in _MODE_PATTERNS):
            continue
        if "esc to interrupt" in s:
            continue
        if _PROMPT_RE.match(s):
            continue
        _content_lines.append(s)
    last_output = "\n".join(_content_lines[-3:]) if _content_lines else ""

    # ── Content change detection ──────────────────────────────
    # Hash the meaningful content (skip blanks/separators) to detect
    # screen changes between polls.  If content changed significantly,
    # Claude is streaming output — even without explicit indicators.
    import hashlib
    content_hash = hashlib.md5(output.encode()).hexdigest()[:12]
    content_changed = (
        previous_state is not None
        and previous_state._content_hash != ""
        and previous_state._content_hash != content_hash
    )

    # ── Detect mode + working indicator from status bar (last 5 lines) ──
    mode = "normal"
    is_interruptable = False
    for line in lines[-5:]:
        stripped = line.strip()
        for pattern, mode_name in _MODE_PATTERNS.items():
            if pattern in stripped:
                mode = mode_name
                break
        if "esc to interrupt" in stripped:
            is_interruptable = True

    # "esc to interrupt" means Claude is actively working, regardless
    # of whether the ❯ prompt is visible
    if is_interruptable:
        # Find the thinking detail (e.g., "✻ Waddling...")
        detail = ""
        for line in reversed(lines):
            s = line.strip()
            if _THINKING_RE.search(s):
                detail = s
                break
        return _make_state("thinking", mode, session_name, previous_state, detail, content_hash, last_output=last_output)

    # ── Detect state from content ─────────────────────────────
    # Work backwards from the bottom to find the most recent indicator

    # Get the last ~15 meaningful lines (skip separators and blanks)
    meaningful = []
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _SEPARATOR_RE.match(stripped):
            continue
        # Skip mode indicator lines
        if any(p in stripped for p in _MODE_PATTERNS):
            continue
        meaningful.append(stripped)
        if len(meaningful) >= 15:
            break

    if not meaningful:
        return _make_state("idle", mode, session_name, previous_state, last_output=last_output)

    top = meaningful[0]  # most recent meaningful line (bottom of screen)

    # Check for empty prompt (idle) — but only if screen content is stable.
    # If content just changed, Claude is still streaming output.
    if _PROMPT_RE.match(top):
        if content_changed:
            return _make_state("responding", mode, session_name, previous_state, "", content_hash, last_output=last_output)
        return _make_state("idle", mode, session_name, previous_state, "", content_hash, last_output=last_output)

    # Check for thinking indicators
    if _THINKING_RE.search(top):
        detail = top.strip()
        return _make_state("thinking", mode, session_name, previous_state, detail, last_output=last_output)

    # Check for numbered selection
    if _SELECTION_RE.match(top):
        return _make_state("selecting", mode, session_name, previous_state, top.strip(), last_output=last_output)

    # Check for permission prompt
    if _PERMISSION_RE.search(top):
        return _make_state("permission", mode, session_name, previous_state, top.strip(), last_output=last_output)

    # Check for tool execution (! prefix)
    if _TOOL_RE.match(top):
        return _make_state("tool_running", mode, session_name, previous_state, top.strip(), last_output=last_output)

    # Check for Claude response streaming (⏺ prefix)
    if _RESPONSE_RE.match(top):
        return _make_state("responding", mode, session_name, previous_state, last_output=last_output)

    # Check if prompt has user input (user is typing)
    if _PROMPT_INPUT_RE.match(top):
        return _make_state("idle", mode, session_name, previous_state, last_output=last_output)

    # Check recent lines for active indicators
    for line in meaningful[:5]:
        if _THINKING_RE.search(line):
            return _make_state("thinking", mode, session_name, previous_state, line.strip(), last_output=last_output)
        if _TOOL_RE.match(line):
            return _make_state("tool_running", mode, session_name, previous_state, line.strip(), last_output=last_output)

    # Default: if content is changing, Claude is working
    if content_changed:
        return _make_state("responding", mode, session_name, previous_state, "", content_hash, last_output=last_output)
    return _make_state("busy", mode, session_name, previous_state, "", content_hash, last_output=last_output)


def _make_state(
    state: str,
    mode: str,
    session_name: str,
    previous: ClaudeState | None,
    detail: str = "",
    content_hash: str = "",
    last_output: str = "",
) -> ClaudeState:
    """Create a ClaudeState, preserving ``since`` if state unchanged."""
    since = time.time()
    if previous and previous.state == state:
        since = previous.since  # keep the original timestamp
    return ClaudeState(
        state=state,
        detail=detail,
        mode=mode,
        since=since,
        session_name=session_name,
        _content_hash=content_hash,
        last_output=last_output,
    )
