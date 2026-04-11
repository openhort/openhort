"""Stream parser for Claude Code's stream-json output format.

Reads newline-delimited JSON from a subprocess stdout and yields
structured events that callers can consume without knowing the
wire protocol.
"""

from __future__ import annotations

import json
import subprocess
from typing import Generator


def stream_response(
    proc: subprocess.Popen[bytes],
) -> Generator[tuple[str, str | dict], None, None]:
    """Parse stream-json output from a Claude CLI process.

    Expected input: newline-delimited JSON on ``proc.stdout``, produced by
    ``claude -p --output-format stream-json --verbose --include-partial-messages``.

    Yields:
        ("text", chunk)  — a fragment of Claude's visible text response
        ("meta", dict)   — final metadata with usage:
            session_id, total_cost_usd, total_input_tokens,
            total_output_tokens, num_turns, duration_ms

    All other event types (thinking, signatures, rate-limit, message
    start/stop) are silently skipped.
    """
    session_id: str | None = None

    assert proc.stdout is not None
    # readline() avoids Python's 8 KB read-ahead buffer so text
    # arrives at the consumer immediately, one JSON line at a time.
    for raw_line in iter(proc.stdout.readline, b""):
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")

        if etype == "system" and event.get("subtype") == "init":
            session_id = event.get("session_id")

        elif etype == "stream_event":
            inner = event.get("event", {})
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield ("text", delta.get("text", ""))

        elif etype == "result":
            if not session_id:
                session_id = event.get("session_id")
            yield ("meta", {
                "session_id": session_id,
                "total_cost_usd": event.get("total_cost_usd", 0),
                "total_input_tokens": event.get("total_input_tokens", 0),
                "total_output_tokens": event.get("total_output_tokens", 0),
                "num_turns": event.get("num_turns", 0),
                "duration_ms": event.get("duration_ms", 0),
                # Keep legacy key for backward compat
                "cost": event.get("total_cost_usd", 0),
            })

    proc.wait()
