"""Envoy host client — connects to the Envoy's control channel.

Runs on the host. Connects to the Envoy inside a container via
TCP (docker exec port forward or mapped port). Pushes tool definitions,
proxies tool calls to openhort, returns results.

Also supports the reverse direction: discovers container-local tools
and exposes them to the host.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class EnvoyClient:
    """Host-side client for the Envoy control channel.

    Usage::

        client = EnvoyClient(tool_handler=my_tool_executor)
        await client.connect("localhost", 9198)
        await client.register_tools([...])
        # Tool calls from the Envoy arrive at my_tool_executor
        # and results are sent back automatically.
    """

    def __init__(self, tool_handler: ToolHandler | None = None) -> None:
        self._tool_handler = tool_handler
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._listen_task: asyncio.Task[None] | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, host: str = "localhost", port: int = 9198) -> None:
        """Connect to the Envoy's control channel."""
        self._reader, self._writer = await asyncio.open_connection(host, port)
        self._connected = True
        self._listen_task = asyncio.create_task(self._listen())
        logger.info("Connected to Envoy at %s:%d", host, port)

    async def disconnect(self) -> None:
        self._connected = False
        if self._listen_task:
            self._listen_task.cancel()
        if self._writer:
            self._writer.close()

    async def register_tools(self, tools: list[dict[str, Any]]) -> None:
        """Push tool definitions to the Envoy."""
        await self._send({"type": "register_tools", "tools": tools})
        logger.info("Registered %d tools with Envoy", len(tools))

    async def ping(self) -> bool:
        """Ping the Envoy, wait for pong."""
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending["__ping__"] = future
        await self._send({"type": "ping"})
        try:
            await asyncio.wait_for(future, timeout=5.0)
            return True
        except asyncio.TimeoutError:
            return False

    async def set_credential(self, name: str, value: str) -> None:
        """Provision a credential in the Envoy's in-memory store."""
        await self._send({"type": "set_credential", "name": name, "value": value})

    async def request_local_tools(self) -> list[dict[str, Any]]:
        """Ask the Envoy what container-local tools are available (reverse direction)."""
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending["__local_tools__"] = future
        await self._send({"type": "request_local_tools"})
        try:
            result = await asyncio.wait_for(future, timeout=10.0)
            return result.get("tools", [])
        except asyncio.TimeoutError:
            return []

    async def call_local_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a container-local tool (reverse direction)."""
        import uuid
        call_id = str(uuid.uuid4())[:8]
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[call_id] = future
        await self._send({"type": "call_local_tool", "id": call_id, "name": name, "args": args or {}})
        try:
            result = await asyncio.wait_for(future, timeout=60.0)
            return result.get("result", {})
        except asyncio.TimeoutError:
            return {"content": [{"type": "text", "text": f"Timeout calling local tool: {name}"}], "isError": True}

    # ── Internal ──

    async def _send(self, msg: dict[str, Any]) -> None:
        if not self._writer:
            raise ConnectionError("Not connected to Envoy")
        data = json.dumps(msg) + "\n"
        self._writer.write(data.encode())
        await self._writer.drain()

    async def _listen(self) -> None:
        """Read messages from the Envoy."""
        assert self._reader is not None
        try:
            while self._connected:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                await self._handle_message(msg)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._connected = False
            logger.info("Disconnected from Envoy")

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type", "")

        if msg_type == "tool_call":
            # Envoy is asking us to execute a dynamic tool
            call_id = msg.get("id", "")
            name = msg.get("name", "")
            args = msg.get("args", {})

            if self._tool_handler:
                try:
                    result = await self._tool_handler(name, args)
                except Exception as exc:
                    result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
            else:
                result = {"content": [{"type": "text", "text": f"No tool handler for: {name}"}], "isError": True}

            await self._send({"type": "tool_result", "id": call_id, "result": result})

        elif msg_type == "pong":
            future = self._pending.pop("__ping__", None)
            if future and not future.done():
                future.set_result(msg)

        elif msg_type == "local_tools":
            future = self._pending.pop("__local_tools__", None)
            if future and not future.done():
                future.set_result(msg)

        elif msg_type == "local_tool_result":
            call_id = msg.get("id", "")
            future = self._pending.pop(call_id, None)
            if future and not future.done():
                future.set_result(msg)
