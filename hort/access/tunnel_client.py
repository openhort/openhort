"""Tunnel client — connects an openhort host to the access proxy server.

Run on the openhort host machine to make it accessible through the
access server. Maintains a persistent WebSocket tunnel and relays
HTTP requests and WebSocket connections.

Usage:
    python -m hort.access.tunnel_client --server https://access.example.com --key <connection_key>
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TunnelClient:
    """Connects to the access server and relays requests to the local openhort."""

    def __init__(
        self,
        access_server_url: str,
        connection_key: str,
        local_url: str = "http://localhost:8940",
    ) -> None:
        self._server_url = access_server_url.rstrip("/")
        self._key = connection_key
        self._local_url = local_url.rstrip("/")
        self._ws: Any = None
        self._local_ws_connections: dict[str, Any] = {}  # ws_id → local WS

    async def run(self) -> None:
        """Connect to the access server and start relaying."""
        import websockets

        ws_url = self._server_url.replace("http://", "ws://").replace("https://", "wss://")
        tunnel_url = f"{ws_url}/api/access/tunnel?key={self._key}"

        logger.info("Connecting to access server: %s", self._server_url)

        while True:
            try:
                async with websockets.connect(tunnel_url) as ws:
                    self._ws = ws
                    logger.info("Connected to access server")
                    await self._message_loop(ws)
            except Exception as e:
                logger.warning("Tunnel disconnected: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)

    async def _message_loop(self, ws: Any) -> None:
        """Process messages from the access server."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "http_request":
                    asyncio.create_task(self._handle_http(ws, msg))
                elif msg_type == "ws_open":
                    asyncio.create_task(self._handle_ws_open(ws, msg))
                elif msg_type == "ws_data":
                    asyncio.create_task(self._handle_ws_data(msg))
                elif msg_type == "ws_close":
                    asyncio.create_task(self._handle_ws_close(msg))
            except Exception as e:
                logger.exception("Error handling tunnel message: %s", e)

    async def _handle_http(self, ws: Any, msg: dict[str, Any]) -> None:
        """Proxy an HTTP request to the local openhort instance."""
        req_id = msg.get("req_id", "")
        method = msg.get("method", "GET")
        path = msg.get("path", "/")
        headers = msg.get("headers", {})
        body = msg.get("body", "").encode("latin-1")

        url = f"{self._local_url}{path}"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.request(
                    method, url,
                    headers={k: v for k, v in headers.items() if k.lower() not in ("host", "transfer-encoding")},
                    content=body,
                    timeout=30.0,
                )
                await ws.send(json.dumps({
                    "type": "http_response",
                    "req_id": req_id,
                    "status": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": resp.content.decode("latin-1"),
                }))
        except Exception as e:
            await ws.send(json.dumps({
                "type": "http_response",
                "req_id": req_id,
                "status": 502,
                "headers": {},
                "body": f"Local openhort error: {e}",
            }))

    async def _handle_ws_open(self, tunnel_ws: Any, msg: dict[str, Any]) -> None:
        """Open a local WebSocket connection."""
        import websockets

        ws_id = msg.get("ws_id", "")
        path = msg.get("path", "/")
        local_ws_url = self._local_url.replace("http://", "ws://").replace("https://", "wss://")

        try:
            local_ws = await websockets.connect(f"{local_ws_url}{path}")
            self._local_ws_connections[ws_id] = local_ws

            # Forward local WS messages back through the tunnel
            async def forward() -> None:
                try:
                    async for data in local_ws:
                        if isinstance(data, bytes):
                            await tunnel_ws.send(json.dumps({
                                "type": "ws_data",
                                "ws_id": ws_id,
                                "binary": base64.b64encode(data).decode(),
                            }))
                        else:
                            await tunnel_ws.send(json.dumps({
                                "type": "ws_data",
                                "ws_id": ws_id,
                                "text": data,
                            }))
                except Exception:
                    pass
                finally:
                    self._local_ws_connections.pop(ws_id, None)

            asyncio.create_task(forward())
        except Exception as e:
            logger.warning("Failed to open local WS %s: %s", path, e)

    async def _handle_ws_data(self, msg: dict[str, Any]) -> None:
        """Forward data to a local WebSocket."""
        ws_id = msg.get("ws_id", "")
        local_ws = self._local_ws_connections.get(ws_id)
        if local_ws is None:
            return
        try:
            if "text" in msg:
                await local_ws.send(msg["text"])
            elif "binary" in msg:
                await local_ws.send(base64.b64decode(msg["binary"]))
        except Exception:
            pass

    async def _handle_ws_close(self, msg: dict[str, Any]) -> None:
        """Close a local WebSocket."""
        ws_id = msg.get("ws_id", "")
        local_ws = self._local_ws_connections.pop(ws_id, None)
        if local_ws:
            try:
                await local_ws.close()
            except Exception:
                pass


def main() -> None:  # pragma: no cover
    """Entry point for the tunnel client."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="openhort tunnel client")
    parser.add_argument("--server", required=True, help="Access server URL (e.g. http://localhost:8400)")
    parser.add_argument("--key", required=True, help="Connection key from the access server")
    parser.add_argument("--local", default="http://localhost:8940", help="Local openhort URL")
    args = parser.parse_args()

    client = TunnelClient(args.server, args.key, args.local)
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
