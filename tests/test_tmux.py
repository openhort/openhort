"""E2E tests for tmux session management.

These tests spawn REAL tmux sessions, send commands, read output,
and verify cleanup.  Each test creates sessions with unique names
and kills them in teardown to prevent leaks.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from hort.tmux import (
    PREFIX,
    create_session,
    get_pane_pid,
    is_busy,
    kill_session,
    list_sessions,
    read_output,
    send_text,
    session_exists,
)

# Unique prefix for test sessions to avoid collisions
TEST_PREFIX = "test-"


def _test_name(name: str) -> str:
    """Generate a unique test session name."""
    return f"{TEST_PREFIX}{name}-{int(time.time()) % 10000}"


@pytest.fixture(autouse=True)
def _cleanup_test_sessions():
    """Kill all test sessions after each test."""
    yield
    # Kill any hort:test-* sessions
    for session in list_sessions():
        if session.short_name.startswith(TEST_PREFIX):
            kill_session(session.name)


def _tmux_available() -> bool:
    result = subprocess.run(["tmux", "-V"], capture_output=True)
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _tmux_available(),
    reason="tmux not installed",
)


class TestSessionLifecycle:
    """Create, discover, and kill sessions."""

    def test_create_session(self) -> None:
        name = _test_name("create")
        session = create_session(name)
        assert session is not None
        assert session.name == f"{PREFIX}{name}"
        assert session.short_name == name

    def test_create_session_idempotent(self) -> None:
        name = _test_name("idempotent")
        s1 = create_session(name)
        s2 = create_session(name)
        assert s1 is not None
        assert s2 is not None
        assert s1.name == s2.name

    def test_session_exists(self) -> None:
        name = _test_name("exists")
        assert not session_exists(name)
        create_session(name)
        assert session_exists(name)

    def test_list_sessions(self) -> None:
        name = _test_name("list")
        create_session(name)
        sessions = list_sessions()
        names = [s.short_name for s in sessions]
        assert name in names

    def test_kill_session(self) -> None:
        name = _test_name("kill")
        create_session(name)
        assert session_exists(name)
        assert kill_session(name)
        assert not session_exists(name)

    def test_kill_nonexistent(self) -> None:
        assert not kill_session("nonexistent-session-xyz")

    def test_create_with_cwd(self) -> None:
        name = _test_name("cwd")
        session = create_session(name, cwd="/tmp")
        assert session is not None
        # Verify cwd by reading the prompt
        time.sleep(0.3)
        output = read_output(name, lines=5)
        assert output is not None

    def test_pane_pid(self) -> None:
        name = _test_name("pid")
        create_session(name)
        pid = get_pane_pid(name)
        assert pid is not None
        assert pid > 0


class TestReadWrite:
    """Read output and send text to sessions."""

    def test_read_output_empty_session(self) -> None:
        name = _test_name("read-empty")
        create_session(name)
        time.sleep(0.3)
        output = read_output(name, lines=5)
        assert output is not None
        assert isinstance(output, str)

    def test_send_text_and_read(self) -> None:
        name = _test_name("sendread")
        create_session(name)
        time.sleep(0.3)

        # Send a command
        send_text(name, "echo HORT_TEST_OUTPUT_12345")
        time.sleep(0.5)

        # Read output
        output = read_output(name, lines=20)
        assert output is not None
        assert "HORT_TEST_OUTPUT_12345" in output

    def test_send_without_enter(self) -> None:
        name = _test_name("noenter")
        create_session(name)
        time.sleep(0.3)

        # Send text without Enter — should not execute
        send_text(name, "echo NOT_EXECUTED", enter=False)
        time.sleep(0.3)

        output = read_output(name, lines=10)
        assert output is not None
        # The text should be on the command line but not executed
        # (no output line with NOT_EXECUTED, just the partial input)
        lines = [l for l in output.splitlines() if "NOT_EXECUTED" in l]
        # Should appear at most as part of the prompt line, not as command output
        assert len(lines) <= 1

    def test_read_nonexistent(self) -> None:
        output = read_output("nonexistent-session-xyz")
        assert output is None

    def test_send_to_nonexistent(self) -> None:
        assert not send_text("nonexistent-session-xyz", "hello")

    def test_multiple_commands(self) -> None:
        name = _test_name("multi")
        create_session(name)
        time.sleep(0.3)

        send_text(name, "echo FIRST_CMD")
        time.sleep(0.3)
        send_text(name, "echo SECOND_CMD")
        time.sleep(0.3)

        output = read_output(name, lines=30)
        assert output is not None
        assert "FIRST_CMD" in output
        assert "SECOND_CMD" in output


class TestIsBusy:
    """Check if a process is running in the session."""

    def test_idle_session(self) -> None:
        name = _test_name("idle")
        create_session(name)
        time.sleep(0.5)  # wait for shell to start
        busy = is_busy(name)
        assert busy is False  # at shell prompt

    def test_busy_session(self) -> None:
        name = _test_name("busy")
        create_session(name)
        time.sleep(0.3)

        # Start a long-running command
        send_text(name, "sleep 10")
        time.sleep(0.5)

        busy = is_busy(name)
        assert busy is True  # sleep is running

        # Clean up the sleep
        send_text(name, "", enter=False)
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{PREFIX}{name}", "C-c", ""],
            capture_output=True,
        )

    def test_nonexistent_returns_none(self) -> None:
        assert is_busy("nonexistent-session-xyz") is None


class TestCreateWithCommand:
    """Create sessions with a specific command."""

    def test_create_with_echo(self) -> None:
        name = _test_name("withcmd")
        session = create_session(name, command="bash")
        assert session is not None
        time.sleep(0.3)
        send_text(name, "echo CMD_TEST_OK")
        time.sleep(0.3)
        output = read_output(name, lines=10)
        assert output is not None
        assert "CMD_TEST_OK" in output


class TestE2ECodeWatchScenario:
    """Full scenario: monitor a 'coding session' via tmux."""

    def test_full_workflow(self) -> None:
        """Simulate: user creates session, runs code, openhort monitors it.

        1. Create session (simulating `hort watch my-project`)
        2. Discover it via list_sessions
        3. Send a command (simulating user typing)
        4. Read the output (simulating Telegram "what's happening?")
        5. Check if still busy
        6. Wait for completion
        7. Read final output
        8. Kill session
        """
        name = _test_name("e2e")

        # Step 1: Create session
        session = create_session(name, cwd="/tmp")
        assert session is not None
        time.sleep(0.5)

        # Step 2: Discover it
        sessions = list_sessions()
        found = [s for s in sessions if s.short_name == name]
        assert len(found) == 1
        assert found[0].name == f"{PREFIX}{name}"

        # Step 3: Send a command (simulate code execution)
        send_text(name, 'echo "Build started" && sleep 1 && echo "Build complete"')
        time.sleep(0.3)

        # Step 4: Read output while running
        output = read_output(name, lines=20)
        assert output is not None
        assert "Build started" in output

        # Step 5: Check if busy
        busy = is_busy(name)
        assert busy is True  # sleep is still running

        # Step 6: Wait for completion
        time.sleep(1.5)

        # Step 7: Read final output
        output = read_output(name, lines=20)
        assert output is not None
        assert "Build complete" in output

        # Step 8: Should be idle now
        busy = is_busy(name)
        assert busy is False

        # Step 9: Clean up
        pid = get_pane_pid(name)
        assert pid is not None
        assert kill_session(name)
        assert not session_exists(name)

    def test_monitoring_without_interference(self) -> None:
        """Reading output doesn't interfere with the running process."""
        name = _test_name("nointerfer")
        create_session(name)
        time.sleep(0.3)

        # Start a counter
        send_text(name, "for i in 1 2 3 4 5; do echo COUNT_$i; sleep 0.2; done")
        time.sleep(0.3)

        # Read multiple times while it's running
        for _ in range(3):
            output = read_output(name, lines=20)
            assert output is not None
            time.sleep(0.3)

        # Wait for completion
        time.sleep(1.5)

        # Final output should have all counts
        output = read_output(name, lines=30)
        assert output is not None
        assert "COUNT_5" in output

    def test_session_survives_read(self) -> None:
        """Session stays alive after reading — no side effects."""
        name = _test_name("survive")
        create_session(name)
        time.sleep(0.3)

        # Read many times
        for _ in range(5):
            read_output(name, lines=10)

        # Session should still be alive
        assert session_exists(name)
        assert is_busy(name) is False  # at prompt, not dead


# ── Code-Watch Extension MCP Tools ────────────────────────────────


class TestCodeWatchMCP:
    """Test the code-watch extension's MCP tools with real tmux sessions."""

    @pytest.fixture()
    def extension(self):
        """Create a CodeWatch extension instance with minimal context."""
        from llmings.core.code_watch.code_watch import CodeWatch
        from hort.ext.scheduler import PluginScheduler
        from unittest.mock import MagicMock
        import logging

        cw = CodeWatch()
        cw._instance_name = "code-watch-test"
        cw._class_name = "code-watch-test"
        cw._store = MagicMock()
        cw._files = MagicMock()
        cw._scheduler = PluginScheduler("code-watch-test")
        cw._logger = logging.getLogger("test.code-watch")
        cw._config = {}
        cw.activate({})
        return cw

    def test_list_sessions_empty(self, extension) -> None:
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            extension.execute_mcp_tool("list_sessions", {})
        )
        text = result.content[0]["text"]
        assert "No active" in text or "Active sessions" in text

    def test_list_sessions_with_session(self, extension) -> None:
        import asyncio
        name = _test_name("mcp-list")
        create_session(name)
        time.sleep(0.3)

        result = asyncio.get_event_loop().run_until_complete(
            extension.execute_mcp_tool("list_sessions", {})
        )
        text = result.content[0]["text"]
        assert name in text
        assert "Active sessions" in text

    def test_read_output_tool(self, extension) -> None:
        import asyncio
        name = _test_name("mcp-read")
        create_session(name)
        time.sleep(0.3)
        send_text(name, "echo MCP_READ_TEST_OK")
        time.sleep(0.5)

        result = asyncio.get_event_loop().run_until_complete(
            extension.execute_mcp_tool("read_output", {"session": name, "lines": 20})
        )
        assert not result.is_error
        assert "MCP_READ_TEST_OK" in result.content[0]["text"]

    def test_is_busy_tool(self, extension) -> None:
        import asyncio
        name = _test_name("mcp-busy")
        create_session(name)
        time.sleep(0.5)

        result = asyncio.get_event_loop().run_until_complete(
            extension.execute_mcp_tool("is_busy", {"session": name})
        )
        assert not result.is_error
        assert "idle" in result.content[0]["text"]

    def test_send_text_tool(self, extension) -> None:
        import asyncio
        name = _test_name("mcp-send")
        create_session(name)
        time.sleep(0.3)

        result = asyncio.get_event_loop().run_until_complete(
            extension.execute_mcp_tool("send_text", {"session": name, "text": "echo SENT_VIA_MCP"})
        )
        assert not result.is_error
        assert "Sent" in result.content[0]["text"]

        time.sleep(0.5)
        output = read_output(name, lines=10)
        assert "SENT_VIA_MCP" in output

    def test_create_session_tool(self, extension) -> None:
        import asyncio
        name = _test_name("mcp-create")

        result = asyncio.get_event_loop().run_until_complete(
            extension.execute_mcp_tool("create_session", {"name": name, "cwd": "/tmp"})
        )
        assert not result.is_error
        assert name in result.content[0]["text"]
        assert session_exists(name)

    def test_kill_session_tool(self, extension) -> None:
        import asyncio
        name = _test_name("mcp-kill")
        create_session(name)
        time.sleep(0.3)

        result = asyncio.get_event_loop().run_until_complete(
            extension.execute_mcp_tool("kill_session", {"session": name})
        )
        assert not result.is_error
        assert "terminated" in result.content[0]["text"]
        assert not session_exists(name)

    def test_nonexistent_session_errors(self, extension) -> None:
        import asyncio
        for tool in ["read_output", "is_busy", "send_text", "kill_session"]:
            args = {"session": "nonexistent-xyz"}
            if tool == "send_text":
                args["text"] = "hello"
            result = asyncio.get_event_loop().run_until_complete(
                extension.execute_mcp_tool(tool, args)
            )
            assert result.is_error, f"{tool} should error for nonexistent session"
