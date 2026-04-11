"""Tests for the stream-json parser."""

from __future__ import annotations

import io
import json
import subprocess
from unittest.mock import MagicMock

from llmings.core.claude_code.stream import stream_response


def _make_proc(lines: list[str]) -> MagicMock:
    """Create a mock Popen with stdout that supports readline()."""
    proc = MagicMock(spec=subprocess.Popen)
    encoded = [line.encode() + b"\n" for line in lines]
    proc.stdout = io.BytesIO(b"".join(encoded))
    proc.wait.return_value = 0
    return proc


def test_text_delta() -> None:
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": " world"},
            },
        }),
        json.dumps({
            "type": "result", "subtype": "success",
            "session_id": "s1", "total_cost_usd": 0.01,
        }),
    ]
    events = list(stream_response(_make_proc(lines)))

    texts = [d for k, d in events if k == "text"]
    assert texts == ["Hello", " world"]

    meta = [d for k, d in events if k == "meta"]
    assert meta[0]["session_id"] == "s1"
    assert meta[0]["cost"] == 0.01


def test_skips_thinking() -> None:
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "s2"}),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "hmm"},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "OK"},
            },
        }),
        json.dumps({
            "type": "result", "subtype": "success",
            "session_id": "s2", "total_cost_usd": 0.005,
        }),
    ]
    texts = [d for k, d in stream_response(_make_proc(lines)) if k == "text"]
    assert texts == ["OK"]


def test_handles_malformed_lines() -> None:
    lines = [
        "",
        "not json",
        json.dumps({"type": "system", "subtype": "init", "session_id": "s3"}),
        "{broken",
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "fine"},
            },
        }),
        json.dumps({
            "type": "result", "subtype": "success",
            "session_id": "s3", "total_cost_usd": 0.0,
        }),
    ]
    texts = [d for k, d in stream_response(_make_proc(lines)) if k == "text"]
    assert texts == ["fine"]


def test_session_id_from_result() -> None:
    lines = [
        json.dumps({
            "type": "result", "subtype": "success",
            "session_id": "from-result", "total_cost_usd": 0.02,
        }),
    ]
    meta = [d for k, d in stream_response(_make_proc(lines)) if k == "meta"]
    assert meta[0]["session_id"] == "from-result"


def test_ignores_unknown_events() -> None:
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "s4"}),
        json.dumps({"type": "rate_limit_event", "rate_limit_info": {}}),
        json.dumps({"type": "stream_event", "event": {"type": "message_start"}}),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_stop"}}),
        json.dumps({
            "type": "result", "subtype": "success",
            "session_id": "s4", "total_cost_usd": 0.0,
        }),
    ]
    events = list(stream_response(_make_proc(lines)))
    assert all(k == "meta" for k, _ in events)
