"""Integration test for OpenHort's llming-com-backed access tunnel client."""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest
from fastapi import FastAPI, Request, WebSocket

from hort.access.tunnel_client import TunnelClient
from llming_com.access.remote import InMemoryAccessStore, create_access_app


class UvicornThread:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import uvicorn

        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=self.port,
                lifespan="off",
                log_level="warning",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if getattr(self._server, "started", False):
                return
            time.sleep(0.02)
        raise RuntimeError(f"server did not start on {self.port}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _private_app() -> FastAPI:
    app = FastAPI()

    @app.get("/private")
    async def private(request: Request) -> dict[str, str]:
        return {
            "ok": "true",
            "via": request.headers.get("x-forwarded-via", ""),
            "query": request.url.query,
        }

    @app.websocket("/ws/private")
    async def private_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await websocket.send_text("openhort:" + message["text"])

    return app


async def _wait_online(client: httpx.AsyncClient, host_id: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = await client.get("/api/access/hosts")
        response.raise_for_status()
        if any(host["host_id"] == host_id and host["online"] for host in response.json()["hosts"]):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("host did not come online")


@pytest.mark.asyncio
async def test_openhort_tunnel_client_reaches_private_http_and_websocket(tmp_path) -> None:
    store = InMemoryAccessStore()
    store.create_user("admin", "Password123!", "Admin")
    hub = UvicornThread(create_access_app(store))
    private = UvicornThread(_private_app())
    hub.start()
    private.start()
    tunnel: TunnelClient | None = None
    tunnel_task: asyncio.Task[None] | None = None
    try:
        async with httpx.AsyncClient(base_url=hub.url, timeout=10) as browser:
            (await browser.post(
                "/api/access/login",
                json={"username": "admin", "password": "Password123!"},
            )).raise_for_status()
            host = (await browser.post("/api/access/hosts", json={"display_name": "OpenHort"})).json()
            status_file = tmp_path / "hort-tunnel.active"
            tunnel = TunnelClient(
                hub.url,
                host["connection_key"],
                private.url,
                status_file=status_file,
            )
            tunnel_task = asyncio.create_task(tunnel.run())
            await _wait_online(browser, host["host_id"])
            assert status_file.read_text() == f"{hub.url}\n{host['host_id']}"

            response = await browser.get(f"/proxy/{host['host_id']}/private?x=1")
            assert response.status_code == 200
            assert response.json() == {"ok": "true", "via": "proxy", "query": "x=1"}

            import websockets

            cookie = browser.cookies.get("llming_access_session")
            ws_url = hub.url.replace("http://", "ws://") + f"/proxy/{host['host_id']}/ws/private"
            async with websockets.connect(
                ws_url,
                additional_headers={"Cookie": f"llming_access_session={cookie}"},
            ) as websocket:
                await websocket.send("hello")
                assert await websocket.recv() == "openhort:hello"
    finally:
        if tunnel is not None:
            await tunnel.stop()
        if tunnel_task is not None:
            tunnel_task.cancel()
            try:
                await tunnel_task
            except asyncio.CancelledError:
                pass
        hub.stop()
        private.stop()
