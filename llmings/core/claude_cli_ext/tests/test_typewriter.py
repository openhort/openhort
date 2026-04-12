"""Tests for the typewriter display engine."""

from __future__ import annotations

import io
import json
import subprocess
import time
from unittest.mock import MagicMock

import pytest

from llmings.core.claude_cli_ext.typewriter import typewriter


def _make_proc(lines: list[str]) -> MagicMock:
    proc = MagicMock(spec=subprocess.Popen)
    encoded = [line.encode() + b"\n" for line in lines]
    proc.stdout = io.BytesIO(b"".join(encoded))
    proc.wait.return_value = 0
    return proc


def _simple_lines(text: str, session_id: str = "s1") -> list[str]:
    return [
        json.dumps({"type": "system", "subtype": "init", "session_id": session_id}),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        }),
        json.dumps({
            "type": "result", "subtype": "success",
            "session_id": session_id, "total_cost_usd": 0.01,
        }),
    ]


def test_outputs_all_text(capsys: pytest.CaptureFixture[str]) -> None:
    meta = typewriter(_make_proc(_simple_lines("Hello!")))
    captured = capsys.readouterr().out
    assert "Hello!" in captured
    assert meta["session_id"] == "s1"
    assert meta["cost"] == 0.01


def test_strips_leading_newlines(capsys: pytest.CaptureFixture[str]) -> None:
    typewriter(_make_proc(_simple_lines("\n\nHi")))
    captured = capsys.readouterr().out
    assert captured.startswith("Hi")


def test_no_response(capsys: pytest.CaptureFixture[str]) -> None:
    lines = [
        json.dumps({
            "type": "result", "subtype": "success",
            "session_id": "empty", "total_cost_usd": 0.0,
        }),
    ]
    meta = typewriter(_make_proc(lines))
    captured = capsys.readouterr().out
    assert "(no response)" in captured
    assert meta["session_id"] == "empty"


def test_speed_bounds(capsys: pytest.CaptureFixture[str]) -> None:
    text = "A" * 200
    t0 = time.monotonic()
    typewriter(_make_proc(_simple_lines(text)))
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"Too slow: {elapsed:.3f}s"


def test_large_block_drains_fast(capsys: pytest.CaptureFixture[str]) -> None:
    text = "X" * 2000
    t0 = time.monotonic()
    typewriter(_make_proc(_simple_lines(text)))
    elapsed = time.monotonic() - t0
    captured = capsys.readouterr().out
    assert captured.count("X") == 2000
    assert elapsed < 3.0, f"Drain too slow: {elapsed:.3f}s"
