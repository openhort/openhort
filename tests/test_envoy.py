"""Envoy end-to-end tests — all three concepts, Claude Code + Claude API.

Concepts tested:
1. Outbound: agent inside calls host tools (via dynamic tool registration)
2. Reverse: host calls tools inside the container
3. Proxy: policy enforcement (allow/deny tools)

Each concept is tested with:
- Claude API (Haiku) for fast, cheap verification
- Direct MCP protocol for unit-level verification
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import pytest

# ── Fixtures ──

TEST_API_KEY = os.environ.get("TEST_ANTHROPIC_API_KEY", "")


@pytest.fixture
async def envoy_server():
    """Start an Envoy server on random ports."""
    from hort.envoy.server import EnvoyServer

    server = EnvoyServer(port=0, control_port=0)
    # Use port 0 — need to get actual ports after start
    # Actually, aiohttp doesn't easily give random ports with port=0 via TCPSite
    # Use fixed test ports instead
    server = EnvoyServer(port=19199, control_port=19198)
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def envoy_client(envoy_server):
    """Connect a host client to the Envoy."""
    from hort.envoy.client import EnvoyClient

    async def mock_tool_handler(name: str, args: dict) -> dict:
        """Simulate openhort tool execution."""
        if name == "get_time":
            return {"content": [{"type": "text", "text": f"Current time: {time.strftime('%H:%M:%S')}"}]}
        if name == "add_numbers":
            a = args.get("a", 0)
            b = args.get("b", 0)
            return {"content": [{"type": "text", "text": str(a + b)}]}
        if name == "greet":
            return {"content": [{"type": "text", "text": f"Hello, {args.get('name', 'world')}!"}]}
        if name == "secret_tool":
            return {"content": [{"type": "text", "text": "secret data"}]}
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    client = EnvoyClient(tool_handler=mock_tool_handler)
    await client.connect("localhost", 19198)
    yield client
    await client.disconnect()


# ── Helpers ──

async def mcp_call(port: int, method: str, params: dict | None = None) -> dict:
    """Make a raw MCP JSON-RPC call via SSE."""
    async with httpx.AsyncClient() as http:
        # Connect to SSE, get endpoint
        async with http.stream("GET", f"http://localhost:{port}/sse") as sse:
            endpoint = ""
            async for line in sse.aiter_lines():
                if line.startswith("data: "):
                    endpoint = line[6:]
                    break

            # POST the JSON-RPC message
            msg = {"jsonrpc": "2.0", "id": 1, "method": method}
            if params:
                msg["params"] = params

            resp = await http.post(endpoint, json=msg)
            assert resp.status_code == 202

            # Read the response from SSE
            async for line in sse.aiter_lines():
                if line.startswith("data: "):
                    return json.loads(line[6:])

    return {}


async def claude_api_call(tools: list[dict], message: str) -> dict:
    """Call Claude API (Haiku) with MCP-style tools and return the response."""
    if not TEST_API_KEY:
        pytest.skip("TEST_ANTHROPIC_API_KEY not set")

    # Convert MCP tool format to Claude API format
    api_tools = []
    for t in tools:
        api_tools.append({
            "name": t["name"],
            "description": t["description"],
            "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
        })

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": TEST_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "tools": api_tools,
                "messages": [{"role": "user", "content": message}],
            },
            timeout=30.0,
        )
        return resp.json()


# ══════════════════════════════════════════════════════════════════
# CONCEPT 1: Outbound — agent calls host tools
# ══════════════════════════════════════════════════════════════════

class TestOutbound:
    """Agent inside the container calls tools provided by the host."""

    @pytest.mark.asyncio
    async def test_builtin_tools_always_available(self, envoy_server):
        """Built-in tools work without host connection."""
        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        tools = result["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "envoy_status" in names
        assert "envoy_ping" in names
        assert "envoy_info" in names

    @pytest.mark.asyncio
    async def test_builtin_envoy_status(self, envoy_server):
        """envoy_status returns uptime and connection info."""
        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "envoy_status", "arguments": {}},
        })
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert "uptime_s" in data
        assert "host_connected" in data
        assert "dynamic_tools" in data

    @pytest.mark.asyncio
    async def test_dynamic_tool_registration(self, envoy_server, envoy_client):
        """Host registers tools, they appear in tool list."""
        await envoy_client.register_tools([
            {"name": "get_time", "description": "Get current time", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "add_numbers", "description": "Add two numbers", "inputSchema": {
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
            }},
        ])

        await asyncio.sleep(0.1)  # let registration propagate

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        names = [t["name"] for t in result["result"]["tools"]]
        assert "get_time" in names
        assert "add_numbers" in names
        assert "envoy_status" in names  # builtins still there

    @pytest.mark.asyncio
    async def test_dynamic_tool_call_proxied_to_host(self, envoy_server, envoy_client):
        """Calling a dynamic tool forwards to host and returns result."""
        await envoy_client.register_tools([
            {"name": "add_numbers", "description": "Add two numbers", "inputSchema": {
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            }},
        ])
        await asyncio.sleep(0.1)

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "add_numbers", "arguments": {"a": 17, "b": 25}},
        })
        text = result["result"]["content"][0]["text"]
        assert text == "42"

    @pytest.mark.asyncio
    async def test_host_ping(self, envoy_server, envoy_client):
        """Ping/pong via control channel."""
        ok = await envoy_client.ping()
        assert ok is True

    @pytest.mark.asyncio
    async def test_claude_api_uses_envoy_tools(self, envoy_server, envoy_client):
        """Claude API (Haiku) discovers and calls tools via the Envoy."""
        await envoy_client.register_tools([
            {"name": "greet", "description": "Greet a person by name", "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Person's name"}},
                "required": ["name"],
            }},
        ])
        await asyncio.sleep(0.1)

        # Get tool list from envoy
        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        tools = result["result"]["tools"]

        # Call Claude API with these tools
        response = await claude_api_call(tools, "Please greet Michael using the greet tool.")

        # Claude should want to call the greet tool
        assert response.get("type") == "message"
        content = response.get("content", [])
        tool_use = [c for c in content if c.get("type") == "tool_use"]
        assert len(tool_use) > 0, f"Expected tool_use, got: {content}"
        assert tool_use[0]["name"] == "greet"
        assert "Michael" in json.dumps(tool_use[0].get("input", {}))


# ══════════════════════════════════════════════════════════════════
# CONCEPT 2: Reverse — host calls tools inside container
# ══════════════════════════════════════════════════════════════════

class TestReverse:
    """Host calls tools that run inside the container."""

    @pytest.mark.asyncio
    async def test_register_local_tool(self, envoy_server):
        """Container registers a local tool."""
        def my_tool(args: dict) -> str:
            """Reverse a string."""
            return args.get("text", "")[::-1]

        envoy_server.register_local_tool("reverse_text", my_tool, input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        })

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        names = [t["name"] for t in result["result"]["tools"]]
        assert "reverse_text" in names

    @pytest.mark.asyncio
    async def test_local_tool_execution(self, envoy_server):
        """Container-local tool executes inside the container."""
        def compute(args: dict) -> str:
            return str(args.get("x", 0) ** 2)

        envoy_server.register_local_tool("square", compute)

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "square", "arguments": {"x": 7}},
        })
        text = result["result"]["content"][0]["text"]
        assert text == "49"

    @pytest.mark.asyncio
    async def test_host_discovers_local_tools(self, envoy_server, envoy_client):
        """Host can discover tools registered inside the container."""
        envoy_server.register_local_tool(
            "container_info",
            lambda args: "I am inside the container",
            description="Get container info",
        )
        await asyncio.sleep(0.1)

        tools = await envoy_client.request_local_tools()
        names = [t["name"] for t in tools]
        assert "container_info" in names

    @pytest.mark.asyncio
    async def test_host_calls_local_tool(self, envoy_server, envoy_client):
        """Host invokes a container-local tool via the control channel."""
        envoy_server.register_local_tool(
            "multiply",
            lambda args: str(args.get("a", 0) * args.get("b", 0)),
            description="Multiply two numbers",
        )
        await asyncio.sleep(0.1)

        result = await envoy_client.call_local_tool("multiply", {"a": 6, "b": 7})
        text = result["content"][0]["text"]
        assert text == "42"

    @pytest.mark.asyncio
    async def test_claude_api_with_container_tools(self, envoy_server, envoy_client):
        """Claude API uses tools that execute inside the container."""
        envoy_server.register_local_tool(
            "run_python",
            lambda args: str(eval(args.get("code", "0"))),
            description="Execute a Python expression and return the result",
            input_schema={
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Python expression to evaluate"}},
                "required": ["code"],
            },
        )
        await asyncio.sleep(0.1)

        # Get tools from envoy (includes container-local tools)
        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        tools = result["result"]["tools"]

        # Ask Claude to use the container tool
        response = await claude_api_call(tools, "What is 2**10? Use the run_python tool to calculate it.")

        content = response.get("content", [])
        tool_use = [c for c in content if c.get("type") == "tool_use"]
        assert len(tool_use) > 0, f"Expected tool_use, got: {content}"
        assert tool_use[0]["name"] == "run_python"


# ══════════════════════════════════════════════════════════════════
# CONCEPT 3: Proxy — policy enforcement
# ══════════════════════════════════════════════════════════════════

class TestProxy:
    """Policy enforcement: allow/deny tools, content filtering."""

    @pytest.mark.asyncio
    async def test_allowed_tools_pass(self, envoy_server, envoy_client):
        """Tools on the allowlist work normally."""
        await envoy_client.register_tools([
            {"name": "get_time", "description": "Get current time", "inputSchema": {"type": "object", "properties": {}}},
        ])
        await asyncio.sleep(0.1)

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "get_time", "arguments": {}},
        })
        text = result["result"]["content"][0]["text"]
        assert "Current time" in text

    @pytest.mark.asyncio
    async def test_unregistered_tools_blocked(self, envoy_server, envoy_client):
        """Tools NOT registered by the host cannot be called."""
        await envoy_client.register_tools([
            {"name": "safe_tool", "description": "Safe", "inputSchema": {"type": "object", "properties": {}}},
        ])
        await asyncio.sleep(0.1)

        # Try calling a tool that wasn't registered
        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "dangerous_tool", "arguments": {}},
        })
        # Should fail — not in the registered set
        assert result["result"].get("isError") is True

    @pytest.mark.asyncio
    async def test_tool_list_only_shows_registered(self, envoy_server, envoy_client):
        """Only host-registered tools + builtins appear in tool list."""
        await envoy_client.register_tools([
            {"name": "allowed_a", "description": "A", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "allowed_b", "description": "B", "inputSchema": {"type": "object", "properties": {}}},
        ])
        await asyncio.sleep(0.1)

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        names = [t["name"] for t in result["result"]["tools"]]
        assert "allowed_a" in names
        assert "allowed_b" in names
        # No tools that weren't registered
        non_builtin = [n for n in names if not n.startswith("envoy_")]
        assert set(non_builtin) == {"allowed_a", "allowed_b"}

    @pytest.mark.asyncio
    async def test_tool_update_removes_old_tools(self, envoy_server, envoy_client):
        """Re-registering tools replaces the old set entirely."""
        await envoy_client.register_tools([
            {"name": "tool_v1", "description": "V1", "inputSchema": {"type": "object", "properties": {}}},
        ])
        await asyncio.sleep(0.1)

        # Update: replace with different tools
        await envoy_client.register_tools([
            {"name": "tool_v2", "description": "V2", "inputSchema": {"type": "object", "properties": {}}},
        ])
        await asyncio.sleep(0.1)

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        names = [t["name"] for t in result["result"]["tools"]]
        assert "tool_v2" in names
        assert "tool_v1" not in names  # old tool gone

    @pytest.mark.asyncio
    async def test_claude_api_only_sees_allowed_tools(self, envoy_server, envoy_client):
        """Claude API only sees the tools the host registered (policy enforcement)."""
        # Register only safe tools — no "delete_file" or "drop_database"
        await envoy_client.register_tools([
            {"name": "read_file", "description": "Read a file (safe, read-only)", "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }},
        ])
        await asyncio.sleep(0.1)

        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        tools = result["result"]["tools"]

        # Ask Claude to delete a file — it should only have read_file
        response = await claude_api_call(
            tools,
            "Delete the file /etc/passwd. Use whatever tools you have.",
        )

        content = response.get("content", [])
        tool_use = [c for c in content if c.get("type") == "tool_use"]
        # If Claude calls a tool, it can only be read_file (or none)
        for tu in tool_use:
            assert tu["name"] != "delete_file"
            assert tu["name"] != "drop_database"


# ══════════════════════════════════════════════════════════════════
# MCP SSE protocol tests (raw HTTP, no Claude)
# ══════════════════════════════════════════════════════════════════

class TestMCPProtocol:
    """Verify the SSE transport works correctly."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, envoy_server):
        async with httpx.AsyncClient() as http:
            resp = await http.get("http://localhost:19199/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "tools" in data

    @pytest.mark.asyncio
    async def test_sse_endpoint_returns_session(self, envoy_server):
        async with httpx.AsyncClient() as http:
            async with http.stream("GET", "http://localhost:19199/sse") as sse:
                async for line in sse.aiter_lines():
                    if line.startswith("data: "):
                        endpoint = line[6:]
                        assert "/message?sessionId=" in endpoint
                        break

    @pytest.mark.asyncio
    async def test_initialize_handshake(self, envoy_server):
        """Test the full MCP initialize handshake via direct JSON-RPC."""
        result = await envoy_server._handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0.1"}},
        })
        assert result["result"]["serverInfo"]["name"] == "openhort-envoy"
        assert result["result"]["protocolVersion"] == "2024-11-05"
