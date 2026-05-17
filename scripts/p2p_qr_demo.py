"""Run a paired-device P2P demo app reachable from the public OpenHort viewer."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

import qrcode
import uvicorn
import websockets
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from hort.peer2peer.admission import P2PAdmissionClient
from hort.peer2peer.device_tokens import DeviceTokenStore
from hort.peer2peer.webrtc import WebRTCPeer
from llming_com.p2p_proxy import DataChannelProxy, ReconnectTokenStore


LOG = logging.getLogger("p2p_qr_demo")
LOCAL_PORT = 8765
QR_PORT = 8766
RELAY_WS = "wss://relay.openhort.ai"
RELAY_ENDPOINT = os.environ.get("OPENHORT_RELAY_ENDPOINT", RELAY_WS.replace("wss://", "https://").replace("ws://", "http://"))
ADMISSION_KEY = os.environ.get("OPENHORT_ADMISSION_KEY", "")
VIEWER_BASE = "https://openhort.ai/p2p/viewer"


@dataclass
class DemoState:
    room: str
    token: str
    viewer_url: str
    started_at: float
    expires_at: float
    device_store: DeviceTokenStore
    connected: bool = False
    connection_state: str = "waiting"
    offers_seen: int = 0
    token_consumed: bool = False
    admission: P2PAdmissionClient | None = None


def _qr_data_uri(url: str) -> str:
    image = qrcode.make(url)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _private_app(state: DemoState) -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def root() -> HTMLResponse:
        return await viewer()

    @app.get("/viewer")
    async def viewer() -> HTMLResponse:
        now = time.strftime("%H:%M:%S")
        return HTMLResponse(f"""<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>P2P OpenHort Demo</title>
  <style>
    :root {{ color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #111827; color: #f9fafb; }}
    main {{ width: min(560px, calc(100vw - 32px)); }}
    h1 {{ margin: 0 0 12px; font-size: 28px; letter-spacing: 0; }}
    p {{ color: #d1d5db; line-height: 1.45; }}
    dl {{ display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; margin-top: 24px; }}
    dt {{ color: #9ca3af; }}
    dd {{ margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }}
    button {{ margin-top: 24px; padding: 12px 16px; border: 0; border-radius: 8px; font-weight: 700; background: #22c55e; color: #052e16; }}
  </style>
</head>
<body>
  <main>
    <h1>P2P tunnel is live</h1>
    <p>This page was served by a private localhost app through a WebRTC DataChannel. The phone only used the public relay for signaling.</p>
    <dl>
      <dt>Room</dt><dd>{state.room}</dd>
      <dt>Status</dt><dd>{state.connection_state}</dd>
      <dt>Served at</dt><dd>{now}</dd>
    </dl>
    <button onclick="fetch('/api/ping').then(r=>r.json()).then(d=>alert('Private API says: '+d.message))">Ping private API</button>
  </main>
</body>
</html>""")

    @app.get("/api/ping")
    async def ping() -> JSONResponse:
        return JSONResponse({
            "ok": True,
            "message": "hello over P2P",
            "room": state.room,
            "connected": state.connected,
        })

    @app.websocket("/ws/echo")
    async def echo(websocket: Any) -> None:
        await websocket.accept()
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("text") is not None:
                await websocket.send_text("private:" + msg["text"])
            elif msg.get("bytes") is not None:
                await websocket.send_bytes(b"private:" + msg["bytes"])

    return app


def _qr_app(state: DemoState) -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def qr() -> HTMLResponse:
        qr_uri = _qr_data_uri(state.viewer_url)
        return HTMLResponse(f"""<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="3">
  <title>Scan P2P QR</title>
  <style>
    :root {{ color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f3f4f6; color: #111827; }}
    main {{ width: min(520px, calc(100vw - 32px)); text-align: center; }}
    img {{ width: 320px; height: 320px; max-width: 80vw; max-height: 80vw; background: white; border-radius: 8px; padding: 14px; }}
    a {{ color: #2563eb; word-break: break-all; }}
    code {{ display: inline-block; margin-top: 10px; padding: 6px 8px; background: #e5e7eb; border-radius: 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>Scan this P2P QR</h1>
    <img src="{qr_uri}" alt="P2P QR code">
    <p><a href="{state.viewer_url}">{state.viewer_url}</a></p>
    <p><code>{state.connection_state}</code></p>
    <p>This QR pairs the phone once. Reconnect later from the phone's app gallery.</p>
  </main>
</body>
</html>""")

    @app.get("/status")
    async def status() -> JSONResponse:
        return JSONResponse({
            "room": state.room,
            "viewer_url": state.viewer_url,
            "connected": state.connected,
            "connection_state": state.connection_state,
            "offers_seen": state.offers_seen,
            "expires_in": max(0, int(state.expires_at - time.time())),
            "token_consumed": state.token_consumed,
        })

    return app


async def _pending_connect_loop(state: DemoState) -> None:
    admission = state.admission
    if admission is None:
        raise RuntimeError("P2P admission client not configured")
    while True:
        try:
            for req in await admission.pending(state.room):
                token_hash = req.get("device_token_hash", "")
                if not token_hash or not state.device_store.verify_hash(token_hash):
                    continue
                state.device_store.mark_seen(token_hash)
                state.token = secrets.token_urlsafe(32)
                state.token_consumed = False
                state.expires_at = time.time() + 60
                one_time_url = admission.viewer_url(VIEWER_BASE, state.room, token=state.token)
                await admission.respond(state.room, token_hash, one_time_url)
                state.connection_state = "paired device requested reconnect"
            await asyncio.sleep(3)
        except Exception as exc:
            state.connection_state = f"pending poll failed: {exc}"
            await asyncio.sleep(3)


async def _relay_loop(state: DemoState) -> None:
    admission = state.admission
    if admission is None:
        raise RuntimeError("P2P admission client not configured")
    reconnect_tokens = ReconnectTokenStore()
    while True:
        try:
            async with websockets.connect(admission.room_ws_url(state.room)) as ws:
                state.connection_state = "relay connected, waiting for phone"
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") != "offer" or not msg.get("sdp"):
                        continue
                    state.offers_seen += 1
                    reconnect_token = msg.get("reconnect_token", "")
                    token_expired = time.time() > state.expires_at
                    valid_one_time = (
                        msg.get("token") == state.token
                        and not state.token_consumed
                        and not token_expired
                    )
                    valid_reconnect = reconnect_token and reconnect_tokens.verify(reconnect_token)
                    if not valid_one_time and not valid_reconnect:
                        await ws.send(json.dumps({"type": "error", "message": "invalid token"}))
                        continue
                    if valid_one_time:
                        state.token_consumed = True
                    state.connection_state = "creating WebRTC answer"
                    proxy = DataChannelProxy(
                        peer=None,
                        local_base=f"http://127.0.0.1:{LOCAL_PORT}",
                        ws_base=f"ws://127.0.0.1:{LOCAL_PORT}",
                    )

                    async def on_message(data: bytes | str) -> None:
                        await proxy.handle_message(data)

                    async def on_state_change(peer_state: str) -> None:
                        state.connection_state = peer_state
                        state.connected = peer_state == "connected"

                    peer = WebRTCPeer(on_message=on_message, on_state_change=on_state_change)
                    proxy._peer = peer
                    proxy.attach_reconnect_store(reconnect_tokens)
                    answer = await peer.accept_offer(msg["sdp"])
                    await proxy.start()
                    await ws.send(json.dumps({"type": "answer", "sdp": answer}))
                    state.connection_state = "answer sent, connecting"
        except Exception as exc:
            state.connection_state = f"relay reconnecting: {exc}"
            await asyncio.sleep(2)


def _serve(app: FastAPI, port: int) -> None:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    room = "codex-" + secrets.token_urlsafe(12).replace("-", "").replace("_", "")
    admission = P2PAdmissionClient(RELAY_ENDPOINT, ADMISSION_KEY)
    await admission.register_room(room, app_id="openhort.p2p_qr_demo", app_name="P2P Demo")
    token = ""
    device_store = DeviceTokenStore()
    device_token = device_store.create(
        label="Phone",
        app_name="P2P Demo",
        icon="https://openhort.ai/favicon.ico",
    )
    viewer_url = (
        admission.viewer_url(
            VIEWER_BASE,
            room,
            pair=True,
            device=device_token,
            name="P2P Demo",
            icon="https://openhort.ai/favicon.ico",
        )
    )
    state = DemoState(
        room=room,
        token=token,
        viewer_url=viewer_url,
        started_at=time.time(),
        expires_at=time.time() + 600,
        device_store=device_store,
        admission=admission,
    )

    threading.Thread(target=_serve, args=(_private_app(state), LOCAL_PORT), daemon=True).start()
    threading.Thread(target=_serve, args=(_qr_app(state), QR_PORT), daemon=True).start()
    LOG.info("QR page: http://127.0.0.1:%d", QR_PORT)
    LOG.info("Phone URL: %s", viewer_url)
    await asyncio.gather(_relay_loop(state), _pending_connect_loop(state))


if __name__ == "__main__":
    asyncio.run(main())
