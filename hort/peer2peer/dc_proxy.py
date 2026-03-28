"""DataChannel proxy — multiplexes HTTP and WebSocket over a WebRTC DataChannel.

The browser sends serialized HTTP requests and WebSocket frames through the
DataChannel. This proxy demuxes them, forwards to localhost, and sends
responses back through the DataChannel.

Protocol (JSON envelope for control, binary for WS frames):

  Request:  {"id": "r1", "type": "http", "method": "POST", "path": "/api/session", "headers": {...}, "body": "..."}
  Response: {"id": "r1", "type": "http_response", "status": 200, "headers": {...}, "body": "..."}

  WS open:  {"id": "w1", "type": "ws_open", "path": "/ws/control/abc123"}
  WS ready: {"id": "w1", "type": "ws_ready"}
  WS text:  {"id": "w1", "type": "ws_text", "data": "..."}
  WS bin:   first 4 bytes = "w1\x00\x00" (id padded to 4 bytes), rest = binary payload
  WS close: {"id": "w1", "type": "ws_close"}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import websockets  # type: ignore[import-untyped]

from hort.peer2peer.webrtc import WebRTCPeer

logger = logging.getLogger(__name__)

# WebSocket ID is encoded as first 4 bytes of binary messages
WS_ID_LEN = 4


class DataChannelProxy:
    """Proxies HTTP and WebSocket traffic over a WebRTC DataChannel.

    Each instance manages one peer connection's proxy traffic.
    Also handles video_config messages to dynamically adjust
    the video track's resolution, FPS, and window target.
    """


    def __init__(
        self,
        peer: WebRTCPeer,
        local_base: str = "http://127.0.0.1:8940",
        ws_base: str = "ws://127.0.0.1:8940",
    ) -> None:
        self._peer = peer
        self._local_base = local_base
        self._ws_base = ws_base
        self._ws_connections: dict[str, Any] = {}  # id → websocket
        self._http_client: httpx.AsyncClient | None = None
        self._video_track: Any = None  # ScreenCaptureTrack, set externally
        # Static cache is shared across all sessions (class-level)
        # Assets like Vue, Quasar, CSS don't change between connections

    async def start(self) -> None:
        """Start the proxy. Call after DataChannel is open."""
        self._http_client = httpx.AsyncClient(base_url=self._local_base, timeout=30.0)

    async def stop(self) -> None:
        """Stop the proxy and clean up connections."""
        for ws_id, ws in list(self._ws_connections.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self._ws_connections.clear()
        if self._http_client:
            await self._http_client.aclose()

    async def handle_message(self, data: bytes | str) -> None:
        """Handle an incoming message from the DataChannel."""
        if isinstance(data, bytes):
            await self._handle_ws_binary(data)
            return

        try:
            msg = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return

        msg_type = msg.get("type", "")

        if msg_type == "ping":
            # Immediate echo — no async, no processing
            await self._peer.send(json.dumps({"type": "pong", "ts": msg.get("ts", 0)}))
            return
        elif msg_type == "http":
            asyncio.create_task(self._handle_http(msg))
        elif msg_type == "ws_open":
            asyncio.create_task(self._handle_ws_open(msg))
        elif msg_type == "ws_text":
            await self._handle_ws_text(msg)
        elif msg_type == "ws_close":
            await self._handle_ws_close(msg)
        elif msg_type == "video_config":
            self._handle_video_config(msg)

    def _handle_video_config(self, msg: dict[str, Any]) -> None:
        """Dynamically adjust the video track's settings.

        Handles FPS, window target, and viewport updates (position, zoom,
        client resolution) for viewport-aware streaming.
        """
        if not self._video_track:
            return

        if "fps" in msg:
            self._video_track.fps = int(msg["fps"])
            logger.info("video fps → %d", self._video_track.fps)

        if "window_id" in msg:
            self._video_track.set_window(int(msg["window_id"]))
            logger.info("video window → %d", msg["window_id"])

        # Viewport updates (position, zoom, client resolution)
        viewport_keys = {"viewport_x", "viewport_y", "viewport_w", "viewport_h",
                         "client_width", "client_height", "zoom"}
        if viewport_keys & msg.keys():
            self._video_track.update_viewport(msg)
            vp = self._video_track.viewport
            logger.debug(
                "viewport → (%.2f,%.2f) %.2fx%.2f zoom=%.1f client=%dx%d",
                vp.x, vp.y, vp.w, vp.h, vp.zoom,
                vp.client_width, vp.client_height,
            )

    async def _handle_http(self, msg: dict[str, Any]) -> None:
        """Proxy an HTTP request to localhost and send the response back."""
        req_id = msg.get("id", "")
        method = msg.get("method", "GET")
        path = msg.get("path", "/")
        headers = msg.get("headers", {})
        body = msg.get("body")

        if not self._http_client:
            return

        try:
            headers.pop("host", None)
            headers.pop("Host", None)

            resp = await self._http_client.request(
                method=method,
                url=path,
                headers=headers,
                content=body.encode() if body else None,
            )

            import base64
            content_type = resp.headers.get("content-type", "")
            is_text = any(t in content_type for t in ("text/", "application/json", "application/javascript", "/xml", "/svg"))
            if is_text or not content_type:
                resp_body = resp.text
                is_binary = False
            else:
                resp_body = base64.b64encode(resp.content).decode()
                is_binary = True

            response = {
                "id": req_id,
                "type": "http_response",
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp_body,
                "binary": is_binary,
            }
            await self._peer.send(json.dumps(response))

        except Exception as exc:
            error_resp = {
                "id": req_id,
                "type": "http_response",
                "status": 502,
                "headers": {},
                "body": str(exc),
            }
            await self._peer.send(json.dumps(error_resp))

    async def _handle_ws_open(self, msg: dict[str, Any]) -> None:
        """Open a WebSocket to localhost and bridge it to the DataChannel."""
        ws_id = msg.get("id", "")
        path = msg.get("path", "")
        url = self._ws_base + path

        try:
            ws = await websockets.connect(url)
            self._ws_connections[ws_id] = ws

            # Notify client that WS is ready
            await self._peer.send(json.dumps({"id": ws_id, "type": "ws_ready"}))

            # Start reading from the local WS and forwarding to DataChannel
            asyncio.create_task(self._ws_read_loop(ws_id, ws))

        except Exception as exc:
            await self._peer.send(json.dumps({
                "id": ws_id,
                "type": "ws_close",
                "reason": str(exc),
            }))

    async def _ws_read_loop(self, ws_id: str, ws: Any) -> None:
        """Read from local WebSocket and forward to DataChannel.

        Binary frames (JPEG stream) use a single-slot buffer — only the
        latest frame is kept. If a new frame arrives before the previous
        one was sent, the old one is dropped. This prevents frame piling
        and ensures the DataChannel stays responsive for control messages.
        """
        id_bytes = ws_id.encode()[:WS_ID_LEN].ljust(WS_ID_LEN, b"\x00")
        _latest_binary: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        _running = True

        async def _sender() -> None:
            while _running:
                try:
                    data = await asyncio.wait_for(_latest_binary.get(), timeout=1.0)
                    await self._peer.send(id_bytes + data)
                except TimeoutError:
                    continue
                except Exception:
                    break

        send_task = asyncio.create_task(_sender())

        try:
            async for message in ws:
                if isinstance(message, str):
                    await self._peer.send(json.dumps({
                        "id": ws_id,
                        "type": "ws_text",
                        "data": message,
                    }))
                else:
                    # Single-slot: drop old frame, keep latest
                    if _latest_binary.full():
                        try:
                            _latest_binary.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    _latest_binary.put_nowait(message)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as exc:
            logger.debug("WS read loop error for %s: %s", ws_id, exc)
        finally:
            _running = False
            send_task.cancel()
            self._ws_connections.pop(ws_id, None)
            try:
                await self._peer.send(json.dumps({"id": ws_id, "type": "ws_close"}))
            except Exception:
                pass

    async def _handle_ws_text(self, msg: dict[str, Any]) -> None:
        """Forward a text WebSocket message to localhost.

        Also intercepts stream_config messages to update the video track's
        viewport/window configuration.
        """
        ws_id = msg.get("id", "")
        data = msg.get("data", "")

        # Intercept stream_config to update video track
        if data and self._video_track:
            try:
                ws_msg = json.loads(data)
                if ws_msg.get("type") == "stream_config":
                    window_id = ws_msg.get("window_id")
                    if window_id is not None:
                        self._video_track.set_window(int(window_id))
                    fps = ws_msg.get("fps")
                    if fps is not None:
                        self._video_track.fps = int(fps)
                    # Map screen_width/screen_dpr to client resolution
                    sw = ws_msg.get("screen_width", 0)
                    dpr = ws_msg.get("screen_dpr", 1.0)
                    if sw > 0:
                        self._video_track.update_viewport({
                            "client_width": int(sw * dpr),
                            "client_height": int(sw * dpr * 9 / 16),  # assume 16:9
                        })
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        ws = self._ws_connections.get(ws_id)
        if ws:
            try:
                await ws.send(data)
            except Exception:
                pass

    async def _handle_ws_binary(self, data: bytes) -> None:
        """Forward a binary WebSocket message to localhost."""
        if len(data) < WS_ID_LEN:
            return
        ws_id = data[:WS_ID_LEN].rstrip(b"\x00").decode()
        payload = data[WS_ID_LEN:]
        ws = self._ws_connections.get(ws_id)
        if ws:
            try:
                await ws.send(payload)
            except Exception:
                pass

    async def _handle_ws_close(self, msg: dict[str, Any]) -> None:
        """Close a proxied WebSocket."""
        ws_id = msg.get("id", "")
        ws = self._ws_connections.pop(ws_id, None)
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
