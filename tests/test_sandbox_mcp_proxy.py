"""Tests for the MCP SSE proxy and ProxyManager."""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
import time

import pytest

from hort.sandbox.mcp import McpServerConfig, ToolFilter
from hort.sandbox.mcp_proxy import McpSseProxy, ProxyManager

# A minimal MCP server that speaks the stdio protocol.
# It responds to initialize and tools/list, and echoes tools/call.
MOCK_MCP_SCRIPT = textwrap.dedent("""\
    import sys, json

    def read_msg():
        content_length = None
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                sys.exit(0)
            text = line.decode().strip()
            if not text:
                if content_length is not None:
                    break
                continue
            if text.lower().startswith("content-length:"):
                content_length = int(text.split(":", 1)[1].strip())
        if content_length is None:
            sys.exit(0)
        body = sys.stdin.buffer.read(content_length)
        return json.loads(body)

    def write_msg(msg):
        body = json.dumps(msg).encode()
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\\r\\n\\r\\n".encode())
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

    while True:
        try:
            msg = read_msg()
        except Exception:
            break

        method = msg.get("method")
        msg_id = msg.get("id")

        if method == "initialize":
            write_msg({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock-mcp", "version": "1.0"},
                    "protocolVersion": "2024-11-05",
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            write_msg({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": [
                    {"name": "read_file", "description": "Read a file",
                     "inputSchema": {"type": "object", "properties": {
                         "path": {"type": "string"}}}},
                    {"name": "write_file", "description": "Write a file",
                     "inputSchema": {"type": "object", "properties": {
                         "path": {"type": "string"},
                         "content": {"type": "string"}}}},
                    {"name": "delete_file", "description": "Delete a file",
                     "inputSchema": {"type": "object", "properties": {
                         "path": {"type": "string"}}}},
                ]},
            })
        elif method == "tools/call":
            tool = msg.get("params", {}).get("name", "unknown")
            write_msg({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [
                    {"type": "text", "text": f"called:{tool}"},
                ]},
            })
        elif msg_id is not None:
            write_msg({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": "Method not found"},
            })
""")


def _mock_config(**kwargs: object) -> McpServerConfig:
    """Config that runs the mock MCP script."""
    return McpServerConfig(
        command=sys.executable,
        args=["-c", MOCK_MCP_SCRIPT],
        **kwargs,  # type: ignore[arg-type]
    )


async def _sse_connect(
    port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, str]:
    """Connect to the proxy's SSE endpoint.

    Returns (reader, writer, endpoint_url).
    """
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
            # Read trailing blank line
            await reader.readline()
            break

    return reader, writer, endpoint_url


async def _post_message(
    port: int, endpoint_path: str, msg: dict
) -> None:
    """POST a JSON-RPC message to the proxy."""
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
    # Read response
    await asyncio.wait_for(reader.read(4096), timeout=5)
    writer.close()


async def _read_sse_event(reader: asyncio.StreamReader) -> dict:
    """Read one SSE message event and return parsed JSON."""
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


# ── McpSseProxy tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_start_and_url() -> None:
    proxy = McpSseProxy("test", _mock_config())
    await proxy.start()
    try:
        assert proxy._actual_port > 0
        assert "localhost" in proxy.url
        assert str(proxy._actual_port) in proxy.url
        assert "host.docker.internal" in proxy.host_url
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_proxy_sse_endpoint_event() -> None:
    proxy = McpSseProxy("test", _mock_config())
    await proxy.start()
    try:
        reader, writer, endpoint = await _sse_connect(proxy._actual_port)
        assert "/message?sessionId=" in endpoint
        writer.close()
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_proxy_message_roundtrip() -> None:
    """Send initialize + tools/list and verify responses come back on SSE."""
    proxy = McpSseProxy("test", _mock_config())
    await proxy.start()
    try:
        reader, writer, endpoint = await _sse_connect(proxy._actual_port)

        # Send initialize
        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"capabilities": {}},
        })
        resp = await _read_sse_event(reader)
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "mock-mcp"

        # Send tools/list
        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        resp = await _read_sse_event(reader)
        assert resp["id"] == 2
        tool_names = [t["name"] for t in resp["result"]["tools"]]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "delete_file" in tool_names

        writer.close()
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_proxy_tools_call() -> None:
    """Send a tools/call and verify the response."""
    proxy = McpSseProxy("test", _mock_config())
    await proxy.start()
    try:
        reader, writer, endpoint = await _sse_connect(proxy._actual_port)

        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "/etc/hosts"}},
        })
        resp = await _read_sse_event(reader)
        assert resp["id"] == 1
        assert resp["result"]["content"][0]["text"] == "called:read_file"

        writer.close()
    finally:
        await proxy.stop()


# ── Tool filtering via proxy ──────────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_filter_allow_list() -> None:
    """tools/list should only return allowed tools."""
    config = _mock_config(
        tool_filter=ToolFilter(allow=["read_file"]),
    )
    proxy = McpSseProxy("test", config)
    await proxy.start()
    try:
        reader, writer, endpoint = await _sse_connect(proxy._actual_port)

        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        resp = await _read_sse_event(reader)
        tool_names = [t["name"] for t in resp["result"]["tools"]]
        assert tool_names == ["read_file"]

        writer.close()
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_proxy_filter_deny_list() -> None:
    """tools/list should exclude denied tools."""
    config = _mock_config(
        tool_filter=ToolFilter(deny=["delete_file"]),
    )
    proxy = McpSseProxy("test", config)
    await proxy.start()
    try:
        reader, writer, endpoint = await _sse_connect(proxy._actual_port)

        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        resp = await _read_sse_event(reader)
        tool_names = [t["name"] for t in resp["result"]["tools"]]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "delete_file" not in tool_names

        writer.close()
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_proxy_blocks_denied_tool_call() -> None:
    """tools/call for a denied tool should return an error."""
    config = _mock_config(
        tool_filter=ToolFilter(deny=["delete_file"]),
    )
    proxy = McpSseProxy("test", config)
    await proxy.start()
    try:
        reader, writer, endpoint = await _sse_connect(proxy._actual_port)

        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "delete_file", "arguments": {"path": "/x"}},
        })
        resp = await _read_sse_event(reader)
        assert "error" in resp
        assert resp["error"]["code"] == -32601
        assert "not allowed" in resp["error"]["message"]

        writer.close()
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_proxy_allows_permitted_tool_call() -> None:
    """tools/call for an allowed tool should succeed normally."""
    config = _mock_config(
        tool_filter=ToolFilter(allow=["read_file"]),
    )
    proxy = McpSseProxy("test", config)
    await proxy.start()
    try:
        reader, writer, endpoint = await _sse_connect(proxy._actual_port)

        # Allowed tool
        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "read_file", "arguments": {}},
        })
        resp = await _read_sse_event(reader)
        assert "result" in resp

        # Blocked tool
        await _post_message(proxy._actual_port, endpoint, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "write_file", "arguments": {}},
        })
        resp = await _read_sse_event(reader)
        assert "error" in resp

        writer.close()
    finally:
        await proxy.stop()


# ── ProxyManager tests ────────────────────────────────────────────


def test_proxy_manager_lifecycle() -> None:
    """ProxyManager starts proxies and returns URLs, stops cleanly."""
    servers = {
        "mock1": _mock_config(),
        "mock2": _mock_config(),
    }
    mgr = ProxyManager()
    urls = mgr.start(servers, container_mode=False)
    try:
        assert "mock1" in urls
        assert "mock2" in urls
        assert "localhost" in urls["mock1"]
        assert "localhost" in urls["mock2"]
        assert urls["mock1"] != urls["mock2"]  # different ports
    finally:
        mgr.stop()


def test_proxy_manager_container_mode_urls() -> None:
    """Container mode should use host.docker.internal URLs."""
    servers = {"mock": _mock_config()}
    mgr = ProxyManager()
    urls = mgr.start(servers, container_mode=True)
    try:
        assert "host.docker.internal" in urls["mock"]
    finally:
        mgr.stop()


def test_proxy_manager_empty() -> None:
    """Empty server dict returns empty URLs, no crash."""
    mgr = ProxyManager()
    urls = mgr.start({}, container_mode=False)
    assert urls == {}
    mgr.stop()  # should not crash


def test_proxy_manager_stop_idempotent() -> None:
    """Calling stop() multiple times is safe."""
    mgr = ProxyManager()
    mgr.stop()
    mgr.stop()
