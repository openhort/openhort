"""End-to-end tests for the MCP bridge — both core logic and SSE transport.

Tests verify the full protocol roundtrip:
  fake plugin → MCPBridge → SSE transport → HTTP client
"""

from __future__ import annotations

import asyncio
import json
import textwrap
import sys

import pytest

from .bridge import MCPBridge, MCPSseServer
from .fake_plugins import (
    FakeCalculatorPlugin,
    FakeErrorPlugin,
    FakeMemoryPlugin,
)


# ── Helpers ──────────────────────────────────────────────────────


def _bridge(*plugins) -> MCPBridge:
    return MCPBridge(list(plugins))


async def _sse_connect(
    port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, str]:
    """Connect to SSE endpoint, return (reader, writer, endpoint_url)."""
    reader, writer = await asyncio.open_connection("localhost", port)
    writer.write(
        f"GET /sse HTTP/1.1\r\n"
        f"Host: localhost:{port}\r\n"
        f"\r\n".encode()
    )
    await writer.drain()

    # Read HTTP response headers
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        if line.strip() == b"":
            break

    # Read the endpoint event
    endpoint_url = ""
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        decoded = line.decode().strip()
        if decoded.startswith("data:"):
            endpoint_url = decoded[5:].strip()
            await reader.readline()  # trailing blank
            break

    return reader, writer, endpoint_url


async def _post_message(port: int, endpoint_path: str, msg: dict) -> None:
    """POST a JSON-RPC message."""
    body = json.dumps(msg).encode()
    reader, writer = await asyncio.open_connection("localhost", port)
    writer.write(
        f"POST {endpoint_path} HTTP/1.1\r\n"
        f"Host: localhost:{port}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n".encode() + body
    )
    await writer.drain()
    await asyncio.wait_for(reader.read(4096), timeout=5)
    writer.close()


async def _read_sse_event(reader: asyncio.StreamReader) -> dict:
    """Read one SSE message event."""
    event_type = ""
    data = ""
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        decoded = line.decode().strip()
        if not decoded:
            if event_type == "message" and data:
                return json.loads(data)
            continue
        if decoded.startswith("event:"):
            event_type = decoded[6:].strip()
        elif decoded.startswith("data:"):
            data = decoded[5:].strip()


# ── MCPBridge core tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_initialize() -> None:
    bridge = _bridge(FakeMemoryPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"capabilities": {}},
    })
    assert resp is not None
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "openhort-mcp-bridge"
    assert resp["result"]["protocolVersion"] == "2024-11-05"


@pytest.mark.asyncio
async def test_notifications_initialized_returns_none() -> None:
    bridge = _bridge(FakeMemoryPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "method": "notifications/initialized",
    })
    assert resp is None


@pytest.mark.asyncio
async def test_tools_list_single_plugin() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    })
    tools = resp["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "calc__add" in names
    assert "calc__multiply" in names
    assert len(tools) == 2


@pytest.mark.asyncio
async def test_tools_list_multiple_plugins() -> None:
    bridge = _bridge(FakeCalculatorPlugin(), FakeMemoryPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    })
    tools = resp["result"]["tools"]
    names = sorted(t["name"] for t in tools)
    assert names == [
        "calc__add",
        "calc__multiply",
        "memory__get_note",
        "memory__list_notes",
        "memory__save_note",
    ]


@pytest.mark.asyncio
async def test_tools_list_has_descriptions() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    })
    add_tool = next(t for t in resp["result"]["tools"] if t["name"] == "calc__add")
    assert "[calc]" in add_tool["description"]
    assert "Add two numbers" in add_tool["description"]
    assert add_tool["inputSchema"]["required"] == ["a", "b"]


@pytest.mark.asyncio
async def test_tools_call_calculator() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "calc__add", "arguments": {"a": 3, "b": 7}},
    })
    assert resp["result"]["content"][0]["text"] == "10"
    assert resp["result"]["isError"] is False


@pytest.mark.asyncio
async def test_tools_call_multiply() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "calc__multiply", "arguments": {"a": 4, "b": 5}},
    })
    assert resp["result"]["content"][0]["text"] == "20"


@pytest.mark.asyncio
async def test_tools_call_memory_roundtrip() -> None:
    """Save a note then retrieve it — verifies stateful plugin behavior."""
    plugin = FakeMemoryPlugin()
    bridge = _bridge(plugin)

    # Save
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "memory__save_note", "arguments": {"key": "todo", "text": "buy milk"}},
    })
    assert "Saved" in resp["result"]["content"][0]["text"]

    # Retrieve
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "memory__get_note", "arguments": {"key": "todo"}},
    })
    assert resp["result"]["content"][0]["text"] == "buy milk"

    # List
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "memory__list_notes", "arguments": {}},
    })
    assert resp["result"]["content"][0]["text"] == "todo"


@pytest.mark.asyncio
async def test_tools_call_unknown_tool() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "nonexistent__tool", "arguments": {}},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_tools_call_no_namespace() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "add", "arguments": {}},
    })
    assert "error" in resp


@pytest.mark.asyncio
async def test_tools_call_exception_handling() -> None:
    """Plugin that raises should return isError result, not crash the bridge."""
    bridge = _bridge(FakeErrorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "buggy__crash", "arguments": {}},
    })
    assert resp["result"]["isError"] is True
    assert "intentional crash" in resp["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_unknown_method() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_unknown_notification() -> None:
    bridge = _bridge(FakeCalculatorPlugin())
    resp = await bridge.handle_message({
        "jsonrpc": "2.0", "method": "notifications/unknown",
    })
    assert resp is None


# ── SSE transport tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_sse_server_start_stop() -> None:
    server = MCPSseServer(_bridge(FakeCalculatorPlugin()))
    await server.start()
    try:
        assert server.port > 0
        assert "localhost" in server.url
        assert "host.docker.internal" in server.host_url
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_endpoint_event() -> None:
    server = MCPSseServer(_bridge(FakeCalculatorPlugin()))
    await server.start()
    try:
        reader, writer, endpoint = await _sse_connect(server.port)
        assert "/message?sessionId=" in endpoint
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_initialize_roundtrip() -> None:
    server = MCPSseServer(_bridge(FakeCalculatorPlugin()))
    await server.start()
    try:
        reader, writer, endpoint = await _sse_connect(server.port)

        await _post_message(server.port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"capabilities": {}},
        })
        resp = await _read_sse_event(reader)
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "openhort-mcp-bridge"

        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_tools_list() -> None:
    server = MCPSseServer(_bridge(FakeCalculatorPlugin(), FakeMemoryPlugin()))
    await server.start()
    try:
        reader, writer, endpoint = await _sse_connect(server.port)

        await _post_message(server.port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        resp = await _read_sse_event(reader)
        names = sorted(t["name"] for t in resp["result"]["tools"])
        assert "calc__add" in names
        assert "memory__save_note" in names

        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_tools_call() -> None:
    server = MCPSseServer(_bridge(FakeCalculatorPlugin()))
    await server.start()
    try:
        reader, writer, endpoint = await _sse_connect(server.port)

        await _post_message(server.port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "calc__multiply", "arguments": {"a": 6, "b": 7}},
        })
        resp = await _read_sse_event(reader)
        assert resp["result"]["content"][0]["text"] == "42"

        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_stateful_memory_roundtrip() -> None:
    """Full E2E: save + retrieve a note over SSE transport."""
    plugin = FakeMemoryPlugin()
    server = MCPSseServer(_bridge(plugin))
    await server.start()
    try:
        reader, writer, endpoint = await _sse_connect(server.port)

        # Save note
        await _post_message(server.port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "memory__save_note", "arguments": {"key": "k1", "text": "hello world"}},
        })
        resp = await _read_sse_event(reader)
        assert "Saved" in resp["result"]["content"][0]["text"]

        # Retrieve note
        await _post_message(server.port, endpoint, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "memory__get_note", "arguments": {"key": "k1"}},
        })
        resp = await _read_sse_event(reader)
        assert resp["result"]["content"][0]["text"] == "hello world"

        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_error_tool() -> None:
    server = MCPSseServer(_bridge(FakeErrorPlugin()))
    await server.start()
    try:
        reader, writer, endpoint = await _sse_connect(server.port)

        await _post_message(server.port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "buggy__crash", "arguments": {}},
        })
        resp = await _read_sse_event(reader)
        assert resp["result"]["isError"] is True

        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_404() -> None:
    """Unknown path returns 404."""
    server = MCPSseServer(_bridge(FakeCalculatorPlugin()))
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("localhost", server.port)
        writer.write(
            f"GET /unknown HTTP/1.1\r\n"
            f"Host: localhost:{server.port}\r\n"
            f"\r\n".encode()
        )
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=5)
        assert b"404" in data
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_sse_bad_json() -> None:
    """POST with invalid JSON returns 400."""
    server = MCPSseServer(_bridge(FakeCalculatorPlugin()))
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("localhost", server.port)
        bad_body = b"not json"
        writer.write(
            f"POST /message?sessionId=fake HTTP/1.1\r\n"
            f"Host: localhost:{server.port}\r\n"
            f"Content-Length: {len(bad_body)}\r\n"
            f"\r\n".encode() + bad_body
        )
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=5)
        assert b"400" in data
        writer.close()
    finally:
        await server.stop()


# ── Stdio transport test (subprocess) ────────────────────────────


@pytest.mark.asyncio
async def test_stdio_roundtrip() -> None:
    """Spawn the bridge as a subprocess in stdio mode and verify roundtrip."""
    script = textwrap.dedent("""\
        import asyncio
        import sys
        sys.path.insert(0, "{project_root}")
        from subprojects.mcp_bridge.bridge import MCPBridge, run_stdio
        from subprojects.mcp_bridge.fake_plugins import FakeCalculatorPlugin

        bridge = MCPBridge([FakeCalculatorPlugin()])
        asyncio.run(run_stdio(bridge))
    """.format(project_root=_project_root()))

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdin and proc.stdout

    # Send initialize
    _write_msg(proc.stdin, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"capabilities": {}},
    })
    await proc.stdin.drain()
    resp = await _read_msg(proc.stdout)
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "openhort-mcp-bridge"

    # Send tools/list
    _write_msg(proc.stdin, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
    })
    await proc.stdin.drain()
    resp = await _read_msg(proc.stdout)
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "calc__add" in names

    # Send tools/call
    _write_msg(proc.stdin, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "calc__add", "arguments": {"a": 100, "b": 200}},
    })
    await proc.stdin.drain()
    resp = await _read_msg(proc.stdout)
    assert resp["result"]["content"][0]["text"] == "300"

    proc.stdin.close()
    await proc.wait()


def _project_root() -> str:
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent.parent)


def _write_msg(stdin: asyncio.StreamWriter, msg: dict) -> None:
    stdin.write(json.dumps(msg).encode() + b"\n")


async def _read_msg(stdout: asyncio.StreamReader) -> dict:
    while True:
        line = await asyncio.wait_for(stdout.readline(), timeout=5)
        if not line:
            raise EOFError("stdio closed")
        text = line.decode().strip()
        if text:
            return json.loads(text)
