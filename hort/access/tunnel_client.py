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
from pathlib import Path
from typing import Any

import zlib

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
        self._http_client: httpx.AsyncClient | None = None

    async def run(self) -> None:
        """Connect to the access server and start relaying."""
        import websockets

        ws_url = self._server_url.replace("http://", "ws://").replace("https://", "wss://")
        tunnel_url = f"{ws_url}/api/access/tunnel?key={self._key}"

        # Write status file so the openhort UI can show tunnel state
        status_file = Path("/tmp/hort-tunnel.active")

        logger.info("Connecting to access server: %s", self._server_url)

        while True:
            try:
                async with websockets.connect(tunnel_url) as ws:
                    self._ws = ws
                    # Read welcome message to get host_id
                    host_id = ""
                    try:
                        welcome_raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        welcome = json.loads(welcome_raw)
                        if welcome.get("type") == "welcome":
                            host_id = welcome.get("host_id", "")
                            logger.info("Assigned host_id: %s", host_id)
                    except Exception as e:
                        logger.warning("No welcome message: %s", e)
                    # Write status: server_url\nhost_id
                    status_file.write_text(f"{self._server_url}\n{host_id}")
                    logger.info("Connected to access server")
                    await self._message_loop(ws)
            except Exception as e:
                logger.warning("Tunnel disconnected: %s. Reconnecting in 5s...", e)
                try:
                    status_file.unlink(missing_ok=True)
                except OSError:
                    pass
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
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=30.0)
            client = self._http_client
            async with asyncio.timeout(30):
                resp = await client.request(
                    method, url,
                    headers={k: v for k, v in headers.items() if k.lower() not in ("host", "transfer-encoding")},
                    content=body,
                )
                # Split large responses into small WS messages
                # Azure's WS proxy silently drops messages > ~64KB
                body_b64 = base64.b64encode(resp.content).decode("ascii")
                CHUNK = 32000
                if len(body_b64) <= CHUNK:
                    await ws.send(json.dumps({
                        "type": "http_response",
                        "req_id": req_id,
                        "status": resp.status_code,
                        "headers": dict(resp.headers),
                        "body_b64": body_b64,
                    }))
                else:
                    chunks = [body_b64[i:i + CHUNK] for i in range(0, len(body_b64), CHUNK)]
                    for i, chunk in enumerate(chunks):
                        await ws.send(json.dumps({
                            "type": "http_response_start" if i == 0 else "http_response_chunk",
                            "req_id": req_id,
                            **({"status": resp.status_code, "headers": dict(resp.headers), "total_chunks": len(chunks)} if i == 0 else {}),
                            "chunk_index": i,
                            "chunk": chunk,
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

            # Forward local WS messages back through the tunnel.
            # Binary frames (JPEG stream) are dropped if the tunnel
            # can't keep up — prevents unbounded memory growth.
            async def forward() -> None:
                _send_lock = asyncio.Lock()
                _dropping = False
                try:
                    async for data in local_ws:
                        if isinstance(data, bytes):
                            # Drop binary frames if previous send is
                            # still in progress (backpressure).
                            if _send_lock.locked():
                                if not _dropping:
                                    _dropping = True
                                    logger.debug("Tunnel backpressure: dropping frames for ws %s", ws_id)
                                continue
                            _dropping = False
                            async with _send_lock:
                                await tunnel_ws.send(json.dumps({
                                    "type": "ws_data",
                                    "ws_id": ws_id,
                                    "binary": base64.b64encode(data).decode(),
                                }))
                        else:
                            # Text messages (JSON control) are never dropped
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
