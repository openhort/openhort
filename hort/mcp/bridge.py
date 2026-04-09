"""MCP Bridge — serves llming tools over MCP protocol.

Supports two transports:
  - stdio: Newline-delimited JSON-RPC on stdin/stdout (for local Claude)
  - SSE:   HTTP server with GET /sse + POST /message (for container Claude)

The bridge aggregates tools from multiple llming instances,
namespacing them as ``{plugin_id}__{tool_name}`` to avoid collisions.

This module has NO dependency on the extension registry — it works with
any object that satisfies the ``MCPToolProvider`` protocol (which matches
``LlmingBase`` + ``plugin_id``).
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
    """Minimal interface matching LlmingBase — no dependency on hort.ext."""

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
        """Aggregate tools from all providers, namespaced."""
        tools: list[dict[str, Any]] = []
        for pid, provider in self._providers.items():
            for tool in provider.get_mcp_tools():
                tools.append({
                    "name": f"{pid}__{tool.name}",
                    "description": f"[{pid}] {tool.description}",
                    "inputSchema": tool.input_schema or {
                        "type": "object",
                        "properties": {},
                    },
                })
        return tools

    def _resolve_tool(self, namespaced: str) -> tuple[MCPToolProvider, str] | None:
        """Resolve a namespaced tool name to (provider, local_tool_name)."""
        if "__" not in namespaced:
            return None
        pid, tool_name = namespaced.split("__", 1)
        provider = self._providers.get(pid)
        if provider is None:
            return None
        return provider, tool_name

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

    GET  /sse              -> SSE stream (sends endpoint event, then messages)
    POST /message?sessionId=... -> forward JSON-RPC to bridge, response on SSE
    """

    def __init__(
        self, bridge: MCPBridge, host: str = "0.0.0.0", port: int = 0
    ) -> None:
        self._bridge = bridge
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None
        self._actual_port: int = 0
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
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port,
        )
        addr = self._server.sockets[0].getsockname()
        self._actual_port = addr[1]
        logger.info("MCP bridge SSE server on port %d", self._actual_port)

    async def stop(self) -> None:
        for q in list(self._sse_queues.values()):
            await q.put(None)
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=30)
            if not request_line:
                writer.close()
                return

            parts = request_line.decode("utf-8", errors="replace").strip().split(
                " ", 2
            )
            if len(parts) < 2:
                writer.close()
                return
            method, path = parts[0], parts[1]

            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10)
                if line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if ": " in decoded:
                    key, val = decoded.split(": ", 1)
                    headers[key.lower()] = val

            host = headers.get("host", f"localhost:{self._actual_port}")

            if method == "GET" and "/sse" in path:
                await self._handle_sse(writer, host)
            elif method == "POST" and "/message" in path:
                session_id = ""
                if "?" in path:
                    for param in path.split("?", 1)[1].split("&"):
                        if param.startswith("sessionId="):
                            session_id = param.split("=", 1)[1]
                content_length = int(headers.get("content-length", "0"))
                body = b""
                if content_length > 0:
                    body = await asyncio.wait_for(
                        reader.readexactly(content_length), timeout=30,
                    )
                await self._handle_message(writer, session_id, body)
            else:
                writer.write(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
                )
                await writer.drain()
                writer.close()
        except (
            ConnectionError,
            asyncio.IncompleteReadError,
            asyncio.TimeoutError,
        ):
            pass
        except Exception:
            logger.exception("HTTP handler error")
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_sse(
        self, writer: asyncio.StreamWriter, host: str
    ) -> None:
        session_id = str(uuid.uuid4())
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._sse_queues[session_id] = queue

        endpoint = f"http://{host}/message?sessionId={session_id}"
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n"
            b"Access-Control-Allow-Origin: *\r\n"
            b"\r\n"
        )
        await writer.drain()

        writer.write(f"event: endpoint\ndata: {endpoint}\n\n".encode())
        await writer.drain()

        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                data = json.dumps(msg)
                writer.write(f"event: message\ndata: {data}\n\n".encode())
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._sse_queues.pop(session_id, None)
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_message(
        self,
        writer: asyncio.StreamWriter,
        session_id: str,
        body: bytes,
    ) -> None:
        try:
            msg: dict[str, Any] = json.loads(body) if body else {}
        except json.JSONDecodeError:
            writer.write(
                b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"
            )
            await writer.drain()
            writer.close()
            return

        response = await self._bridge.handle_message(msg)
        if response is not None:
            queue = self._sse_queues.get(session_id)
            if queue:
                await queue.put(response)

        writer.write(b"HTTP/1.1 202 Accepted\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
