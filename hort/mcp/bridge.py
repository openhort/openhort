"""MCP Bridge — serves llming tools over MCP protocol.

Supports two transports:
  - stdio: Newline-delimited JSON-RPC on stdin/stdout (for local Claude)
  - SSE:   HTTP server with GET /sse + POST /message (for container Claude)

The bridge aggregates tools from multiple llming instances,
namespacing them as ``{plugin_id}__{tool_name}`` to avoid collisions.

This module has NO dependency on the extension registry — it works with
any object that satisfies the ``MCPToolProvider`` protocol (which matches
``Llming`` + ``plugin_id``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any, Protocol

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"


class MCPToolProvider(Protocol):
    """Minimal interface matching Llming — no dependency on hort.ext."""

    @property
    def plugin_id(self) -> str: ...

    def get_mcp_tools(self) -> list[Any]: ...

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Any: ...


class MCPBridge:
    """Core bridge logic — routes MCP JSON-RPC to plugin instances.

    Transport-agnostic: call ``handle_message()`` with a JSON-RPC dict,
    get back a response dict (or ``None`` for notifications).
    """

    def __init__(self, providers: list[MCPToolProvider]) -> None:
        self._providers = {p.plugin_id: p for p in providers}

    def _all_tools(self) -> list[dict[str, Any]]:
        """Aggregate tools from all providers.

        Single provider: tools use their own names directly (no prefix).
        Multiple providers: tools are namespaced as provider__tool.
        """
        tools: list[dict[str, Any]] = []
        single = len(self._providers) == 1
        for pid, provider in self._providers.items():
            for tool in provider.get_mcp_tools():
                name = tool.name if single else f"{pid}__{tool.name}"
                desc = tool.description if single else f"[{pid}] {tool.description}"
                tools.append({
                    "name": name,
                    "description": desc,
                    "inputSchema": tool.input_schema or {
                        "type": "object",
                        "properties": {},
                    },
                })
        return tools

    def _resolve_tool(self, tool_name: str) -> tuple[MCPToolProvider, str] | None:
        """Resolve a tool name to (provider, local_tool_name).

        Single provider: tool name is passed directly.
        Multiple providers: expects provider__tool format.
        """
        if len(self._providers) == 1:
            provider = next(iter(self._providers.values()))
            return provider, tool_name
        if "__" not in tool_name:
            return None
        pid, local = tool_name.split("__", 1)
        provider = self._providers.get(pid)
        if provider is None:
            return None
        return provider, local

    async def handle_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Process one JSON-RPC message. Returns response or None."""
        method = msg.get("method")
        msg_id = msg.get("id")

        if method == "initialize":
            client_version = msg.get("params", {}).get(
                "protocolVersion", PROTOCOL_VERSION
            )
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "openhort-mcp-bridge", "version": "1.0"},
                    "protocolVersion": client_version,
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self._all_tools()},
            }

        if method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            resolved = self._resolve_tool(tool_name)
            if resolved is None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown tool: {tool_name}",
                    },
                }

            provider, local_name = resolved
            try:
                result = await provider.execute_mcp_tool(local_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": result.content,
                        "isError": result.is_error,
                    },
                }
            except Exception as exc:
                logger.exception("Tool %s execution failed", tool_name)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if msg_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        return None


# ── Stdio transport (newline-delimited JSON) ─────────────────────


async def _read_stdio_line(
    reader: asyncio.StreamReader,
) -> dict[str, Any] | None:
    """Read one newline-delimited JSON-RPC message from stdin."""
    while True:
        line = await reader.readline()
        if not line:
            return None
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        return json.loads(text)


def _write_stdio_line(msg: dict[str, Any]) -> None:
    """Write one newline-delimited JSON-RPC message to stdout."""
    sys.stdout.buffer.write(json.dumps(msg).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


async def run_stdio(bridge: MCPBridge) -> None:
    """Run the bridge as a stdio MCP server (newline-delimited JSON)."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    while True:
        msg = await _read_stdio_line(reader)
        if msg is None:
            break
        response = await bridge.handle_message(msg)
        if response is not None:
            _write_stdio_line(response)


# ── SSE transport ────────────────────────────────────────────────


class MCPSseServer:
    """HTTP server exposing the bridge via MCP SSE transport.

    Uses aiohttp for proper HTTP handling — raw TCP parsers break
    with Node.js MCP clients (Claude Code).

    GET  /sse              -> SSE stream (sends endpoint event, then messages)
    POST /message?sessionId=... -> forward JSON-RPC to bridge, response on SSE
    """

    def __init__(
        self, bridge: MCPBridge, host: str = "0.0.0.0", port: int = 0
    ) -> None:
        self._bridge = bridge
        self._host = host
        self._port = port
        self._actual_port: int = 0
        self._app: Any = None
        self._runner: Any = None
        self._sse_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}

    @property
    def port(self) -> int:
        return self._actual_port

    @property
    def url(self) -> str:
        return f"http://localhost:{self._actual_port}/sse"

    @property
    def host_url(self) -> str:
        return f"http://host.docker.internal:{self._actual_port}/sse"

    async def start(self) -> None:
        from aiohttp import web

        app = web.Application()
        app.router.add_get("/sse", self._handle_sse)
        app.router.add_post("/message", self._handle_message)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()

        # Get the actual port (important when port=0)
        for sock in site._server.sockets:
            addr = sock.getsockname()
            if isinstance(addr, tuple):
                self._actual_port = addr[1]
                break

        self._app = app
        logger.info("MCP bridge SSE server on port %d", self._actual_port)

    async def stop(self) -> None:
        for q in list(self._sse_queues.values()):
            await q.put(None)
        if self._runner:
            await self._runner.cleanup()

    async def _handle_sse(self, request: Any) -> Any:
        from aiohttp import web

        session_id = str(uuid.uuid4())
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._sse_queues[session_id] = queue

        host = request.host
        endpoint = f"http://{host}/message?sessionId={session_id}"

        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        response.headers["Access-Control-Allow-Origin"] = "*"
        await response.prepare(request)

        await response.write(f"event: endpoint\ndata: {endpoint}\n\n".encode())

        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                data = json.dumps(msg)
                await response.write(f"event: message\ndata: {data}\n\n".encode())
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._sse_queues.pop(session_id, None)

        return response

    async def _handle_message(self, request: Any) -> Any:
        from aiohttp import web

        session_id = request.query.get("sessionId", "")
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad Request")

        result = await self._bridge.handle_message(body)
        if result is not None:
            queue = self._sse_queues.get(session_id)
            if queue:
                await queue.put(result)

        return web.Response(status=202, text="Accepted")
