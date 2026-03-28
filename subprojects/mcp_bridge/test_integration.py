"""Integration tests — real Claude Code sessions with the MCP bridge.

These tests spawn the bridge as an MCP server and connect Claude Code
to it via --mcp-config. They verify Claude can discover and use
the in-process plugin tools.

Requires: claude CLI installed, valid API credentials.
Run: poetry run pytest subprojects/mcp_bridge/test_integration.py -v -m integration
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)

# ── Helpers ──────────────────────────────────────────────────────


def _bridge_command() -> list[str]:
    """Command to run the bridge in stdio mode."""
    return [sys.executable, "-m", "subprojects.mcp_bridge"]


def _write_mcp_config(tmpdir: str, mode: str = "stdio", port: int = 0) -> str:
    """Write a Claude-compatible MCP config file. Returns path."""
    if mode == "stdio":
        config = {
            "mcpServers": {
                "openhort": {
                    "command": sys.executable,
                    "args": ["-m", "subprojects.mcp_bridge"],
                    "cwd": PROJECT_ROOT,
                },
            },
        }
    else:
        config = {
            "mcpServers": {
                "openhort": {
                    "type": "sse",
                    "url": f"http://localhost:{port}/sse",
                },
            },
        }

    path = os.path.join(tmpdir, "mcp-config.json")
    with open(path, "w") as f:
        json.dump(config, f)
    return path


def _run_claude(prompt: str, mcp_config: str, timeout: int = 120) -> str:
    """Run claude -p with the given MCP config, return output text."""
    cmd = [
        "claude", "-p",
        "--output-format", "text",
        "--mcp-config", mcp_config,
        "--dangerously-skip-permissions",
        "--max-turns", "5",
        prompt,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=PROJECT_ROOT,
    )
    return result.stdout.strip()


# ── Tests ────────────────────────────────────────────────────────


pytestmark = pytest.mark.integration


class TestStdioBridge:
    """Claude Code connects to the bridge via stdio MCP."""

    def test_claude_discovers_tools(self) -> None:
        """Claude should be able to list and describe the bridge tools."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _write_mcp_config(tmpdir, mode="stdio")
            output = _run_claude(
                "List all available MCP tools from the openhort server. "
                "Just list the tool names, one per line, nothing else.",
                config,
            )
            # Should find our namespaced tools
            assert "calc__add" in output or "calc" in output.lower()
            assert "memory" in output.lower()

    def test_claude_uses_calculator(self) -> None:
        """Claude should call calc__add and return the result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _write_mcp_config(tmpdir, mode="stdio")
            output = _run_claude(
                "Use the calc__add MCP tool to add 1234 and 5678. "
                "Return ONLY the numeric result, nothing else.",
                config,
            )
            assert "6912" in output

    def test_claude_uses_multiply(self) -> None:
        """Claude should call calc__multiply."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _write_mcp_config(tmpdir, mode="stdio")
            output = _run_claude(
                "Use the calc__multiply MCP tool to multiply 42 by 100. "
                "Return ONLY the numeric result, nothing else.",
                config,
            )
            assert "4200" in output

    def test_claude_memory_save_and_retrieve(self) -> None:
        """Claude saves a note then retrieves it in the same session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _write_mcp_config(tmpdir, mode="stdio")
            output = _run_claude(
                "Do these steps using the openhort MCP tools:\n"
                "1. Use memory__save_note to save a note with key='secret' and text='the password is banana'\n"
                "2. Use memory__get_note to retrieve the note with key='secret'\n"
                "3. Reply with ONLY the text content of the retrieved note, nothing else.",
                config,
            )
            assert "banana" in output.lower()


class TestSseBridge:
    """Claude Code connects to the bridge via SSE MCP."""

    @pytest.fixture(autouse=True)
    def _start_sse_server(self):
        """Start the SSE bridge server as a background process."""
        self.sse_proc = subprocess.Popen(
            [sys.executable, "-m", "subprojects.mcp_bridge", "--sse", "--port", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=PROJECT_ROOT,
        )
        # Read first stderr line: "MCP Bridge SSE server running on port XXXXX"
        line = self.sse_proc.stderr.readline().decode()
        self.sse_port = int(line.strip().split("port ")[-1])

        yield

        self.sse_proc.terminate()
        self.sse_proc.wait(timeout=5)

    def test_claude_discovers_tools_via_sse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _write_mcp_config(tmpdir, mode="sse", port=self.sse_port)
            output = _run_claude(
                "List all MCP tools from the openhort server. "
                "Just list the tool names, one per line.",
                config,
            )
            assert "calc" in output.lower()

    def test_claude_uses_calculator_via_sse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _write_mcp_config(tmpdir, mode="sse", port=self.sse_port)
            output = _run_claude(
                "Use the calc__add MCP tool to add 999 and 1. "
                "Return ONLY the numeric result.",
                config,
            )
            assert "1000" in output
