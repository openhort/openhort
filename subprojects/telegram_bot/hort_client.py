"""WebSocket client for hort — mirrors what the browser UI does."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class HortClient:
    """Async client that connects to a hort server via WebSocket.

    Usage:
        async with HortClient("http://localhost:8940") as client:
            windows = await client.list_windows()
            thumb = await client.get_thumbnail(windows[0]["window_id"])
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session_id: str | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._req_counter = 0
        self._reader_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()

    async def connect(self) -> None:
        """Create hort session and connect control WebSocket."""
        self._session = aiohttp.ClientSession()
        try:
            # 1. Create session
            async with self._session.post(f"{self.base_url}/api/session") as resp:
                resp.raise_for_status()
                data = await resp.json()
                self._session_id = data["session_id"]

            # 2. Connect control WS
            ws_url = self.base_url.replace("http://", "ws://").replace(
                "https://", "wss://"
            )
            self._ws = await self._session.ws_connect(
                f"{ws_url}/ws/control/{self._session_id}"
            )

            # 3. Start reader loop
            self._reader_task = asyncio.create_task(self._read_loop())

            # 4. Wait for "connected" message
            await asyncio.wait_for(self._connected.wait(), timeout=self.timeout)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Disconnect and clean up."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        # Cancel pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def __aenter__(self) -> HortClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    # ── High-level commands ──────────────────────────────

    async def list_targets(self) -> list[dict[str, Any]]:
        resp = await self._request("list_targets")
        return resp.get("targets", [])

    async def list_windows(self, app_filter: str = "") -> list[dict[str, Any]]:
        resp = await self._request("list_windows", app_filter=app_filter)
        return resp.get("windows", [])

    async def get_thumbnail(
        self,
        window_id: int,
        target_id: str | None = None,
    ) -> bytes | None:
        """Get a window thumbnail as JPEG bytes (or None on failure)."""
        msg: dict[str, Any] = {"window_id": window_id}
        if target_id:
            msg["target_id"] = target_id
        resp = await self._request("get_thumbnail", **msg)
        b64 = resp.get("data")
        if not b64:
            return None
        return base64.b64decode(b64)

    async def get_status(self) -> dict[str, Any]:
        return await self._request("get_status")

    async def get_spaces(self) -> dict[str, Any]:
        return await self._request("get_spaces")

    async def switch_space(self, index: int) -> dict[str, Any]:
        return await self._request("switch_space", index=index)

    async def set_target(self, target_id: str) -> dict[str, Any]:
        return await self._request("set_target", target_id=target_id)

    async def send_input(self, **kwargs: Any) -> None:
        """Fire-and-forget input event (no response expected)."""
        await self._send({"type": "input", **kwargs})

    async def click(self, nx: float, ny: float) -> None:
        await self.send_input(event_type="click", nx=nx, ny=ny)

    async def send_key(self, key: str, modifiers: list[str] | None = None) -> None:
        await self.send_input(
            event_type="key", key=key, modifiers=modifiers or []
        )

    # ── Internal ─────────────────────────────────────────

    async def _send(self, msg: dict[str, Any]) -> None:
        if not self._ws or self._ws.closed:
            raise ConnectionError("Not connected to hort")
        await self._ws.send_json(msg)

    async def _request(self, msg_type: str, **kwargs: Any) -> dict[str, Any]:
        """Send a request and wait for the matching response."""
        self._req_counter += 1
        req_id = self._req_counter

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut

        await self._send({"type": msg_type, "_req_id": req_id, **kwargs})

        try:
            return await asyncio.wait_for(fut, timeout=self.timeout)
        finally:
            self._pending.pop(req_id, None)

    async def _read_loop(self) -> None:
        """Background task reading WS messages and dispatching to futures."""
        assert self._ws is not None
        try:
            async for ws_msg in self._ws:
                if ws_msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(ws_msg.data)
                    msg_type = data.get("type", "")

                    if msg_type == "connected":
                        self._connected.set()
                        continue

                    if msg_type == "heartbeat":
                        await self._send({"type": "heartbeat_ack"})
                        continue

                    # Match response to pending request
                    req_id = data.get("_req_id")
                    if req_id and req_id in self._pending:
                        self._pending[req_id].set_result(data)
                    # Also handle server-initiated heartbeat_ack etc.

                elif ws_msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("hort WS read loop error")
