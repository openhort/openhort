"""Envoy MCP server — runs inside the container.

Persistent SSE server on localhost:9199. Any MCP client (Claude Code,
OpenAI SDK, Anthropic SDK, custom scripts) connects to the same endpoint.

Tools come from two sources:
1. Built-in (envoy_status, envoy_ping, envoy_info) — always available
2. Dynamic — pushed by the host via the control channel

The control channel is a TCP socket that the host connects to.
The host pushes tool definitions and handles tool call execution.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

# ── Built-in tools ──────────────────────────────────────────────

_BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "envoy_status",
        "description": "Returns Envoy status: uptime, host connection, registered tool count.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "envoy_ping",
        "description": "Test if the host (openhort) is reachable via the control channel.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "envoy_info",
        "description": "Container resource usage: memory, CPU, disk, environment.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _execute_builtin(name: str, _args: dict[str, Any], envoy: EnvoyServer) -> dict[str, Any]:
    """Execute a built-in tool synchronously."""
    if name == "envoy_status":
        return {
            "content": [{"type": "text", "text": json.dumps({
                "uptime_s": round(time.monotonic() - envoy._start_time, 1),
                "host_connected": envoy._control_writer is not None,
                "dynamic_tools": len(envoy._dynamic_tools),
                "total_tools": len(_BUILTIN_TOOLS) + len(envoy._dynamic_tools),
                "container": os.environ.get("HOSTNAME", "unknown"),
            })}],
        }
    if name == "envoy_ping":
        connected = envoy._control_writer is not None
        return {
            "content": [{"type": "text", "text": f"Host {'reachable' if connected else 'NOT connected'}"}],
        }
    if name == "envoy_info":
        info: dict[str, Any] = {
            "hostname": os.environ.get("HOSTNAME", "unknown"),
            "cwd": os.getcwd(),
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - envoy._start_time, 1),
        }
        # Memory from /proc if available (Linux containers)
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        info["rss_kb"] = int(line.split()[1])
        except Exception:
            pass
        return {"content": [{"type": "text", "text": json.dumps(info)}]}
    return {"content": [{"type": "text", "text": f"Unknown builtin: {name}"}], "isError": True}


# ── Envoy Server ────────────────────────────────────────────────

class EnvoyServer:
    """Persistent MCP SSE server with control channel.

    Lifecycle:
    1. Start SSE server on localhost:PORT
    2. Start control channel listener on localhost:CONTROL_PORT
    3. Host connects to control channel, pushes tools
    4. MCP clients connect to SSE, discover tools, make calls
    5. Tool calls for dynamic tools → forwarded to host via control channel
    6. Built-in tool calls → executed locally
    """

    def __init__(self, port: int = 9199, control_port: int = 9198) -> None:
        self._port = port
        self._control_port = control_port
        self._start_time = time.monotonic()

        # MCP state
        self._dynamic_tools: list[dict[str, Any]] = []
        self._sse_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}

        # Control channel
        self._control_reader: asyncio.StreamReader | None = None
        self._control_writer: asyncio.StreamWriter | None = None
        self._pending_calls: dict[str, asyncio.Future[dict[str, Any]]] = {}

        # Reverse direction: container-local tools exposed to host
        self._local_tools: dict[str, Any] = {}  # name → handler callable

        # aiohttp
        self._runner: web.AppRunner | None = None

    @property
    def all_tools(self) -> list[dict[str, Any]]:
        """All tools: built-in + dynamic (from host) + local (from container)."""
        tools = list(_BUILTIN_TOOLS)
        tools.extend(self._dynamic_tools)
        for name, handler in self._local_tools.items():
            tools.append({
                "name": name,
                "description": getattr(handler, "__doc__", "") or f"Container tool: {name}",
                "inputSchema": getattr(handler, "input_schema", {"type": "object", "properties": {}}),
            })
        return tools

    # ── Startup ──

    async def start(self) -> None:
        """Start both SSE server and control channel listener."""
        # SSE server
        app = web.Application()
        app.router.add_get("/sse", self._handle_sse)
        app.router.add_post("/message", self._handle_message)
        app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await site.start()
        logger.info("Envoy MCP SSE server on port %d", self._port)

        # Control channel listener
        server = await asyncio.start_server(
            self._handle_control_connection, "0.0.0.0", self._control_port,
        )
        logger.info("Envoy control channel on port %d", self._control_port)

    async def stop(self) -> None:
        for q in list(self._sse_queues.values()):
            await q.put(None)
        if self._control_writer:
            self._control_writer.close()
        if self._runner:
            await self._runner.cleanup()

    # ── SSE handlers ──

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "uptime_s": round(time.monotonic() - self._start_time, 1),
            "tools": len(self.all_tools),
            "host_connected": self._control_writer is not None,
        })

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
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

    async def _handle_message(self, request: web.Request) -> web.Response:
        session_id = request.query.get("sessionId", "")
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad Request")

        response = await self._handle_jsonrpc(body)
        if response is not None:
            queue = self._sse_queues.get(session_id)
            if queue:
                await queue.put(response)

        return web.Response(status=202, text="Accepted")

    # ── MCP JSON-RPC ──

    async def _handle_jsonrpc(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        msg_id = msg.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "openhort-envoy", "version": "0.1.0"},
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            tools = [
                {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                for t in self.all_tools
            ]
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}

        if method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = await self._execute_tool(tool_name, arguments)
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}

        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Route tool call: builtin → local, container-local → local, dynamic → host."""
        # Built-in?
        builtin_names = {t["name"] for t in _BUILTIN_TOOLS}
        if name in builtin_names:
            return _execute_builtin(name, args, self)

        # Container-local tool?
        if name in self._local_tools:
            handler = self._local_tools[name]
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(args)
                else:
                    result = handler(args)
                if isinstance(result, str):
                    return {"content": [{"type": "text", "text": result}]}
                if isinstance(result, dict):
                    return result
                return {"content": [{"type": "text", "text": str(result)}]}
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}

        # Dynamic tool → forward to host
        if self._control_writer is None:
            return {"content": [{"type": "text", "text": f"Host not connected, cannot call tool: {name}"}], "isError": True}

        return await self._call_host_tool(name, args)

    async def _call_host_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Forward a tool call to the host via control channel, wait for result."""
        call_id = str(uuid.uuid4())[:8]
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_calls[call_id] = future

        msg = json.dumps({"type": "tool_call", "id": call_id, "name": name, "args": args}) + "\n"
        self._control_writer.write(msg.encode())
        await self._control_writer.drain()

        try:
            result = await asyncio.wait_for(future, timeout=60.0)
            return result
        except asyncio.TimeoutError:
            self._pending_calls.pop(call_id, None)
            return {"content": [{"type": "text", "text": f"Tool call timed out: {name}"}], "isError": True}

    # ── Control channel ──

    async def _handle_control_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        """Host connected to control channel."""
        logger.info("Host connected to control channel")
        self._control_reader = reader
        self._control_writer = writer

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                await self._handle_control_message(msg)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            logger.info("Host disconnected from control channel")
            self._control_writer = None
            self._control_reader = None

    async def _handle_control_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type", "")

        if msg_type == "register_tools":
            self._dynamic_tools = msg.get("tools", [])
            logger.info("Registered %d dynamic tools from host", len(self._dynamic_tools))

        elif msg_type == "tool_result":
            call_id = msg.get("id", "")
            future = self._pending_calls.pop(call_id, None)
            if future and not future.done():
                future.set_result(msg.get("result", {}))

        elif msg_type == "ping":
            if self._control_writer:
                resp = json.dumps({"type": "pong"}) + "\n"
                self._control_writer.write(resp.encode())
                await self._control_writer.drain()

        elif msg_type == "request_local_tools":
            # Host asks what tools the container provides (reverse direction)
            tools = [
                {"name": n, "description": getattr(h, "__doc__", "") or n,
                 "inputSchema": getattr(h, "input_schema", {"type": "object", "properties": {}})}
                for n, h in self._local_tools.items()
            ]
            if self._control_writer:
                resp = json.dumps({"type": "local_tools", "tools": tools}) + "\n"
                self._control_writer.write(resp.encode())
                await self._control_writer.drain()

        elif msg_type == "call_local_tool":
            # Host calls a container-local tool (reverse direction)
            call_id = msg.get("id", "")
            name = msg.get("name", "")
            args = msg.get("args", {})
            result = await self._execute_tool(name, args)
            if self._control_writer:
                resp = json.dumps({"type": "local_tool_result", "id": call_id, "result": result}) + "\n"
                self._control_writer.write(resp.encode())
                await self._control_writer.drain()

    # ── Public API for container-local tool registration ──

    def register_local_tool(
        self, name: str, handler: Any, description: str = "", input_schema: dict | None = None,
    ) -> None:
        """Register a tool that runs inside the container.

        These tools are available to MCP clients inside the container
        AND can be exposed to the host (reverse direction).
        """
        if description:
            handler.__doc__ = description
        if input_schema:
            handler.input_schema = input_schema
        self._local_tools[name] = handler
        logger.info("Registered local tool: %s", name)


# ── CLI entry point ──

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="openhort Envoy — MCP server for containers")
    parser.add_argument("--port", type=int, default=9199, help="MCP SSE port (default: 9199)")
    parser.add_argument("--control-port", type=int, default=9198, help="Control channel port (default: 9198)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    async def run() -> None:
        server = EnvoyServer(port=args.port, control_port=args.control_port)
        await server.start()
        logger.info("Envoy ready (MCP on :%d, control on :%d)", args.port, args.control_port)
        await asyncio.Event().wait()

    asyncio.run(run())


if __name__ == "__main__":
    main()
