"""Access proxy server — relays connections between users and remote openhort hosts.

Architecture:
  Browser → Access Server (8400) → openhort host (8940/8950)

The access server:
1. Authenticates users (password + session cookie)
2. Accepts host connections via connection keys (WebSocket tunnel)
3. Proxies HTTP requests and WebSocket connections through the tunnel
4. Shows a host selector when multiple hosts are connected

Host tunnel protocol:
  Host connects: wss://access-server/api/access/tunnel?key=<connection_key>
  Server assigns a tunnel ID.
  All subsequent user traffic for that host is relayed through this tunnel.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from hort.access.auth import (
    RateLimiter,
    hash_password,
    validate_password_strength,
    verify_password,
)
from hort.access.store import FileStore, Store

logger = logging.getLogger(__name__)

# ===== Connected hosts =====


class HostTunnel:
    """A connected openhort host.

    Uses a send queue to avoid concurrent WS send/receive — Starlette
    WebSockets don't support that safely.
    """

    def __init__(self, host_id: str, display_name: str, ws: WebSocket) -> None:
        self.host_id = host_id
        self.display_name = display_name
        self.ws = ws
        self.connected_at = time.monotonic()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_queue: asyncio.Queue[str] = asyncio.Queue()
        self._chunked: dict[str, dict[str, Any]] = {}  # req_id → partial response
        self._ws_clients: dict[str, WebSocket] = {}  # ws_id → browser WebSocket

    async def proxy_request(
        self, method: str, path: str, headers: dict[str, str], body: bytes
    ) -> dict[str, Any]:
        """Send an HTTP request through the tunnel and wait for the response."""
        req_id = secrets.token_hex(8)
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = future
        # Queue the message — the writer task will send it
        await self._send_queue.put(json.dumps({
            "type": "http_request",
            "req_id": req_id,
            "method": method,
            "path": path,
            "headers": headers,
            "body": body.decode("latin-1") if body else "",
        }))
        try:
            resp = await asyncio.wait_for(future, timeout=30.0)
            # Normalize body: decode base64 to raw bytes (stored as "body_bytes")
            if "body_b64" in resp:
                resp["body_bytes"] = base64.b64decode(resp["body_b64"])
                resp.pop("body_b64", None)
            elif "body_zb64" in resp:
                import zlib
                resp["body_bytes"] = zlib.decompress(base64.b64decode(resp["body_zb64"]))
                resp.pop("body_zb64", None)
            elif "body" in resp:
                resp["body_bytes"] = resp["body"].encode("latin-1")
            return resp
        except asyncio.TimeoutError:
            logger.error("Tunnel request timeout: req=%s %s %s", req_id, method, path)
            raise
        finally:
            self._pending.pop(req_id, None)

    async def send_raw(self, msg: str) -> None:
        """Queue a raw JSON message to send through the tunnel."""
        await self._send_queue.put(msg)

    def _finish_chunked(self, req_id: str) -> None:
        """Reassemble chunked response and resolve the pending future."""
        info = self._chunked.pop(req_id, None)
        if not info:
            return
        # Reassemble chunks in order
        body_b64 = "".join(info["chunks"][i] for i in range(info["total"]))
        self.resolve_response(req_id, {
            "status": info["status"],
            "headers": info["headers"],
            "body_b64": body_b64,
        })

    def resolve_response(self, req_id: str, response: dict[str, Any]) -> None:
        """Resolve a pending HTTP request with the host's response."""
        future = self._pending.get(req_id)
        if future and not future.done():
            future.set_result(response)

    async def run(self) -> None:
        """Run the tunnel — concurrent reader and writer on the WS."""

        async def reader() -> None:
            try:
                while True:
                    raw = await self.ws.receive_text()
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")
                    if msg_type == "http_response":
                        self.resolve_response(msg.get("req_id", ""), msg)
                    elif msg_type == "http_response_start":
                        req_id = msg.get("req_id", "")
                        self._chunked[req_id] = {
                            "status": msg.get("status", 200),
                            "headers": msg.get("headers", {}),
                            "total": msg.get("total_chunks", 1),
                            "chunks": {msg.get("chunk_index", 0): msg.get("chunk", "")},
                        }
                        if msg.get("total_chunks", 1) == 1:
                            self._finish_chunked(req_id)
                    elif msg_type == "http_response_chunk":
                        req_id = msg.get("req_id", "")
                        if req_id in self._chunked:
                            self._chunked[req_id]["chunks"][msg.get("chunk_index", 0)] = msg.get("chunk", "")
                            if len(self._chunked[req_id]["chunks"]) >= self._chunked[req_id]["total"]:
                                self._finish_chunked(req_id)
                    elif msg_type == "ws_data":
                        ws_id = msg.get("ws_id", "")
                        client_ws = self._ws_clients.get(ws_id)
                        if client_ws:
                            try:
                                if "binary" in msg:
                                    await client_ws.send_bytes(base64.b64decode(msg["binary"]))
                                elif "text" in msg:
                                    await client_ws.send_text(msg["text"])
                            except Exception:
                                pass
                    elif msg_type == "ws_close":
                        ws_id = msg.get("ws_id", "")
                        client_ws = self._ws_clients.pop(ws_id, None)
                        if client_ws:
                            try:
                                await client_ws.close()
                            except Exception:
                                pass
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.error("Tunnel reader error: %s", e)

        async def writer() -> None:
            try:
                while True:
                    msg = await self._send_queue.get()
                    await self.ws.send_text(msg)
            except (WebSocketDisconnect, Exception):
                pass

        try:
            done, pending = await asyncio.wait(
                [asyncio.create_task(reader()), asyncio.create_task(writer())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Host disconnected"))
            self._pending.clear()


# Global tunnel registry
_tunnels: dict[str, HostTunnel] = {}  # host_id → tunnel

rate_limiter = RateLimiter()


def create_access_app(
    store: Store | None = None,
    static_dir: str | Path | None = None,
) -> FastAPI:
    """Create the access proxy FastAPI application."""
    if store is None:
        store = FileStore()

    app = FastAPI(title="openhort-access", version="0.1.0")
    is_https = os.environ.get("HORT_HTTPS", "0") == "1"
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("ACCESS_SESSION_SECRET") or secrets.token_hex(32),
        https_only=is_https,
        same_site="none" if is_https else "lax",
    )

    if static_dir:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    _register_routes(app, store)


    return app


def _register_routes(app: FastAPI, store: Store) -> None:
    """Register all access server routes."""

    # ===== Auth =====

    @app.post("/api/access/login")
    async def login(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON")
        username = data.get("username", "")
        password = data.get("password", "")
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )

        if not rate_limiter.check(ip):
            raise HTTPException(429, "Too many attempts. Try again later.")

        # Artificial delay for ALL attempts (anti-timing-attack)
        delay = rate_limiter.get_delay(ip)
        await asyncio.sleep(delay)
        rate_limiter.record(ip)

        user = store.get_user(username)
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")

        request.session["username"] = username
        return JSONResponse({"ok": True, "username": username})

    @app.post("/api/access/logout")
    async def logout(request: Request) -> JSONResponse:
        request.session.clear()
        return JSONResponse({"ok": True})

    @app.get("/api/access/me")
    async def me(request: Request) -> JSONResponse:
        username = request.session.get("username")
        if not username:
            raise HTTPException(401, "Not authenticated")
        return JSONResponse({"username": username})

    # ===== Token login (host-verified) =====

    @app.get("/t/{host_id}/{token}")
    async def token_login_short(request: Request, host_id: str, token: str) -> Response:
        """Short URL for token login: /t/{host}/{token}"""
        return await _do_token_login(request, token, host_id)

    @app.get("/api/access/token/login")
    async def token_login(request: Request) -> Response:
        """Login via a token generated on the host (long URL, kept for compat)."""
        token = request.query_params.get("token", "")
        host_id = request.query_params.get("host", "")
        return await _do_token_login(request, token, host_id)

    async def _do_token_login(request: Request, token: str, host_id: str) -> Response:
        """Shared token login logic for both /t/{host}/{token} and /api/access/token/login."""
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )

        if not token or not host_id:
            raise HTTPException(400, "Missing token or host parameter")

        if not rate_limiter.check(ip):
            raise HTTPException(429, "Too many attempts")

        # Artificial delay (same as password auth)
        delay = rate_limiter.get_delay(ip)
        await asyncio.sleep(delay)
        rate_limiter.record(ip)

        # Find the tunnel for this host
        tunnel = _tunnels.get(host_id)
        if tunnel is None:
            raise HTTPException(502, "Host not connected")

        # Ask the host to verify the token
        try:
            resp = await tunnel.proxy_request(
                "POST", "/_internal/verify-token",
                {"content-type": "application/json"},
                json.dumps({"token": token}).encode(),
            )
            if resp.get("status") != 200:
                raise HTTPException(401, "Invalid or expired token")

            body_raw = resp.get("body_bytes", b"{}")
            body = json.loads(body_raw if isinstance(body_raw, (str, bytes)) else "{}")
            if not body.get("valid"):
                raise HTTPException(401, "Invalid or expired token")
        except (ConnectionError, asyncio.TimeoutError):
            raise HTTPException(502, "Host not responding")

        # Token valid — find the host owner and create session
        owner_username = ""
        for u in store.list_users():
            for h in store.get_hosts_for_user(u.username):
                if h.host_id == host_id:
                    owner_username = u.username
                    break
            if owner_username:
                break

        if not owner_username:
            raise HTTPException(401, "Host owner not found")

        request.session["username"] = owner_username
        request.session["host_id"] = host_id
        return RedirectResponse("/viewer", status_code=302)

    # ===== Host management =====

    @app.get("/api/access/hosts")
    async def list_hosts(request: Request) -> JSONResponse:
        username = request.session.get("username")
        if not username:
            raise HTTPException(401, "Not authenticated")
        hosts = store.get_hosts_for_user(username)
        return JSONResponse({
            "hosts": [
                {
                    "host_id": h.host_id,
                    "display_name": h.display_name,
                    "online": h.host_id in _tunnels,
                }
                for h in hosts
            ]
        })

    @app.post("/api/access/select-host")
    async def select_host(request: Request) -> JSONResponse:
        """Set the active host for this session."""
        username = request.session.get("username")
        if not username:
            raise HTTPException(401, "Not authenticated")
        data = await request.json()
        host_id = data.get("host_id", "")
        if host_id:
            request.session["host_id"] = host_id
        return JSONResponse({"ok": True})

    @app.post("/api/access/hosts")
    async def create_host(request: Request) -> JSONResponse:
        username = request.session.get("username")
        if not username:
            raise HTTPException(401, "Not authenticated")
        data = await request.json()
        host = store.create_host(username, data.get("display_name", ""))
        return JSONResponse({
            "host_id": host.host_id,
            "connection_key": host.connection_key,
            "display_name": host.display_name,
        })

    # ===== Host tunnel =====

    @app.websocket("/api/access/tunnel")
    async def host_tunnel(websocket: WebSocket) -> None:
        """WebSocket endpoint for openhort hosts to connect.

        Auth: connection key (required, like an API key).
        Optional: username param for additional verification.
        """
        key = websocket.query_params.get("key", "")
        username = websocket.query_params.get("user", "")

        host_record = store.get_host_by_key(key)
        if host_record is None:
            await websocket.close(code=4003, reason="Invalid connection key")
            return

        # Verify owner still exists
        owner = store.get_user(host_record.owner)
        if owner is None:
            await websocket.close(code=4003, reason="Host owner not found")
            return

        # If username provided, verify it matches the owner
        if username and host_record.owner != username:
            await websocket.close(code=4003, reason="User does not own this host")
            return

        await websocket.accept()
        # Send welcome with host_id so the client knows its identity
        await websocket.send_text(json.dumps({
            "type": "welcome",
            "host_id": host_record.host_id,
            "display_name": host_record.display_name,
        }))
        tunnel = HostTunnel(host_record.host_id, host_record.display_name, websocket)
        _tunnels[host_record.host_id] = tunnel
        logger.info("Host connected: %s (%s)", host_record.display_name, host_record.host_id)

        try:
            await tunnel.run()
        finally:
            _tunnels.pop(host_record.host_id, None)
            logger.info("Host disconnected: %s", host_record.display_name)

    # ===== Transparent proxy =====
    # Once a host is selected (stored in session), ALL non-access-server
    # requests are proxied through the tunnel. URLs identical to LAN.
    # No /proxy/{host_id}/ prefix needed — host comes from session.

    def _get_tunnel(request_or_ws) -> tuple:
        """Get tunnel from session host_id. Returns (host_id, tunnel) or raises."""
        if isinstance(request_or_ws, WebSocket):
            # Parse session cookie manually for WebSocket
            from starlette.middleware.sessions import SessionMiddleware
            host_id = ""
            cookie = request_or_ws.cookies.get("session", "")
            # WebSocket doesn't go through session middleware, use cookie directly
            # Fall back to checking _tunnels for first available
            for hid, t in _tunnels.items():
                return hid, t
            return "", None
        host_id = request_or_ws.session.get("host_id", "")
        if host_id:
            tunnel = _tunnels.get(host_id)
            if tunnel:
                return host_id, tunnel
        # Fall back to first available tunnel for this user
        username = request_or_ws.session.get("username", "")
        if username:
            for h in store.get_hosts_for_user(username):
                if h.host_id in _tunnels:
                    request_or_ws.session["host_id"] = h.host_id
                    return h.host_id, _tunnels[h.host_id]
        return "", None

    # ===== Transparent proxy routes =====
    # Register all known openhort URL prefixes as proxy routes.
    # These are the same URLs as on LAN — the proxy is fully transparent.
    _PROXY_PREFIXES = [
        "/viewer", "/api/{path:path}", "/app/{path:path}", "/ext/{path:path}",
        "/static/{path:path}", "/guide/{path:path}", "/hortmap/{path:path}",
        "/view/{path:path}", "/p2p/{path:path}", "/assets/{path:path}",
        "/rest/{path:path}", "/types/{path:path}", "/favicon.ico",
        "/manifest.json", "/sw.js",
    ]

    # ===== Transparent proxy helper =====

    async def _proxy_path(request: Request, path: str) -> Response:
        """Proxy a request through the tunnel. Host from session."""
        username = request.session.get("username")
        if not username:
            raise HTTPException(404, "Not found")
        host_id = request.session.get("host_id", "")
        tunnel = _tunnels.get(host_id) if host_id else None
        if not tunnel:
            for h in store.get_hosts_for_user(username):
                if h.host_id in _tunnels:
                    tunnel = _tunnels[h.host_id]
                    break
        if not tunnel:
            raise HTTPException(502, "No host connected")
        headers = dict(request.headers)
        headers.pop("host", None)
        headers["X-Forwarded-Via"] = "proxy"
        try:
            resp = await tunnel.proxy_request(request.method, f"/{path}", headers, await request.body())
        except (ConnectionError, asyncio.TimeoutError):
            raise HTTPException(502, "Host not responding")
        body_bytes = resp.get("body_bytes", b"")
        resp_headers = resp.get("headers", {})
        for h in ["content-length", "Content-Length", "transfer-encoding", "connection", "keep-alive"]:
            resp_headers.pop(h, None)
        return Response(content=body_bytes, status_code=resp.get("status", 200), headers=resp_headers)

    # Register transparent proxy for all known openhort prefixes
    # NOTE: Each must be an explicit function (not a loop) to avoid closure issues
    @app.api_route("/viewer", methods=["GET"], name="proxy_viewer2")
    async def pv(request: Request) -> Response:
        return await _proxy_path(request, "viewer")

    @app.api_route("/api/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"], name="proxy_api2")
    async def pa(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"api/{p}")

    @app.api_route("/app/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"], name="proxy_app2")
    async def pap(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"app/{p}")

    @app.api_route("/ext/{p:path}", methods=["GET", "HEAD"], name="proxy_ext2")
    async def pe(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"ext/{p}")

    @app.api_route("/static/{p:path}", methods=["GET", "HEAD"], name="proxy_static2")
    async def ps(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"static/{p}")

    @app.api_route("/assets/{p:path}", methods=["GET", "HEAD"], name="proxy_assets2")
    async def pas(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"assets/{p}")

    @app.api_route("/rest/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"], name="proxy_rest2")
    async def pr(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"rest/{p}")

    @app.api_route("/guide/{p:path}", methods=["GET", "HEAD"], name="proxy_guide2")
    async def pg(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"guide/{p}")

    @app.api_route("/hortmap/{p:path}", methods=["GET", "HEAD"], name="proxy_hortmap2")
    async def ph(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"hortmap/{p}")

    @app.api_route("/view/{p:path}", methods=["GET", "HEAD"], name="proxy_view2")
    async def pvw(request: Request, p: str) -> Response:
        return await _proxy_path(request, f"view/{p}")

    @app.get("/manifest.json", name="proxy_manifest2")
    async def pm(request: Request) -> Response:
        return await _proxy_path(request, "manifest.json")

    @app.get("/sw.js", name="proxy_sw2")
    async def psw(request: Request) -> Response:
        return await _proxy_path(request, "sw.js")

    @app.get("/favicon.ico", name="proxy_favicon2")
    async def pf(request: Request) -> Response:
        return await _proxy_path(request, "favicon.ico")

    # WebSocket proxy — transparent, same URLs as LAN
    @app.websocket("/ws/{path:path}")
    async def ws_transparent(websocket: WebSocket, path: str) -> None:
        _, tunnel = _get_tunnel(websocket)
        if tunnel is None:
            await websocket.close(code=4004, reason="Host not connected")
            return
        await _ws_proxy_impl(websocket, tunnel, f"ws/{path}")

    async def _ws_proxy_impl(websocket: WebSocket, tunnel: Any, path: str) -> None:
        await websocket.accept()
        ws_id = secrets.token_hex(8)
        tunnel._ws_clients[ws_id] = websocket
        await tunnel.send_raw(json.dumps({"type": "ws_open", "ws_id": ws_id, "path": f"/{path}"}))
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.receive":
                    if "text" in msg and msg["text"]:
                        await tunnel.send_raw(json.dumps({"type": "ws_data", "ws_id": ws_id, "text": msg["text"]}))
                    elif "bytes" in msg and msg["bytes"]:
                        import base64
                        await tunnel.send_raw(json.dumps({"type": "ws_data", "ws_id": ws_id, "binary": base64.b64encode(msg["bytes"]).decode()}))
                elif msg["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            tunnel._ws_clients.pop(ws_id, None)
            await tunnel.send_raw(json.dumps({"type": "ws_close", "ws_id": ws_id}))

    # Legacy /proxy/{host_id}/ URLs — set host in session and redirect
    @app.get("/proxy/{host_id}")
    @app.get("/proxy/{host_id}/")
    async def proxy_legacy_root(request: Request, host_id: str) -> Response:
        request.session["host_id"] = host_id
        return Response(status_code=302, headers={"Location": "/viewer"})

    @app.api_route("/proxy/{host_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def proxy_legacy_path(request: Request, host_id: str, path: str) -> Response:
        request.session["host_id"] = host_id
        qs = ("?" + str(request.query_params)) if request.query_params else ""
        return Response(status_code=302, headers={"Location": f"/{path}{qs}"})

    @app.websocket("/ws/{path:path}")
    async def ws_proxy(websocket: WebSocket, path: str) -> None:
        """Proxy WebSocket connections to the host."""
        _, tunnel = _get_tunnel(websocket)
        if tunnel is None:
            await websocket.close(code=4004, reason="Host not connected")
            return

        # Check auth
        # WebSocket requests don't have session middleware auto-parse,
        # but cookies are available
        session_cookie = websocket.cookies.get("session", "")
        if not session_cookie:
            await websocket.close(code=4001, reason="Not authenticated")
            return

        await websocket.accept()

        # Tell the host to open a WS connection
        ws_id = secrets.token_hex(8)
        tunnel._ws_clients[ws_id] = websocket
        await tunnel.send_raw(json.dumps({
            "type": "ws_open",
            "ws_id": ws_id,
            "path": f"/{path}",
        }))

        async def client_to_host() -> None:
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.receive":
                        if "text" in msg and msg["text"]:
                            await tunnel.send_raw(json.dumps({
                                "type": "ws_data",
                                "ws_id": ws_id,
                                "text": msg["text"],
                            }))
                        elif "bytes" in msg and msg["bytes"]:
                            import base64

                            await tunnel.send_raw(json.dumps({
                                "type": "ws_data",
                                "ws_id": ws_id,
                                "binary": base64.b64encode(msg["bytes"]).decode(),
                            }))
                    elif msg["type"] == "websocket.disconnect":
                        break
            except WebSocketDisconnect:
                pass
            finally:
                tunnel._ws_clients.pop(ws_id, None)
                await tunnel.send_raw(json.dumps({
                    "type": "ws_close",
                    "ws_id": ws_id,
                }))

        async def host_to_client() -> None:
            # This is handled by the tunnel's read loop
            # which dispatches ws_data messages back
            # For now, keep the task alive
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass

        try:
            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_host()), asyncio.create_task(host_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        except Exception:
            pass

    # ===== Transparent HTTP proxy =====
    # ALL requests not handled by access server routes are proxied to
    # the host. No /proxy/{host_id}/ prefix — host comes from session.
    # URLs are identical to LAN access.

    async def _proxy_http(request: Request, path: str) -> Response:
        """Proxy an HTTP request through the tunnel. Transparent — same URLs as LAN."""
        username = request.session.get("username")
        if not username:
            # Not logged in — show landing page
            return HTMLResponse(_landing_html())

        host_id, tunnel = _get_tunnel(request)
        if tunnel is None:
            return HTMLResponse("<h2>No host connected</h2><p><a href='/_access'>Back</a></p>", status_code=502)

        body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)
        headers["X-Forwarded-Via"] = "proxy"

        try:
            resp = await tunnel.proxy_request(request.method, f"/{path}", headers, body)
        except (ConnectionError, asyncio.TimeoutError):
            raise HTTPException(502, "Host not responding")

        body_bytes = resp.get("body_bytes", b"")
        resp_headers = resp.get("headers", {})
        # Strip hop-by-hop headers
        for h in ["content-length", "Content-Length", "transfer-encoding", "connection", "keep-alive"]:
            resp_headers.pop(h, None)

        return Response(content=body_bytes, status_code=resp.get("status", 200), headers=resp_headers)

    # ===== Build version =====

    @app.get("/cfversion")
    async def cfversion() -> JSONResponse:
        try:
            build_info = json.loads(Path("/app/build_info.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            build_info = {"version": "dev", "build_time": "unknown"}
        return JSONResponse(build_info)

    # ===== Landing / host selection =====

    @app.get("/_access")
    async def access_landing() -> HTMLResponse:
        return HTMLResponse(_landing_html())

    # Catch-all middleware is registered in create_access_app() after this function.


def _landing_html() -> str:
    """Minimal login page. The real UI is served from the proxied openhort instance."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>openhort access</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/quasar@2.18.7/dist/quasar.prod.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@quasar/extras@1/material-icons/material-icons.css">
<style>
:root { --el-bg: #0a0e1a; --el-surface: #111827; --el-border: #1e3a5f; --el-primary: #3b82f6; --el-text: #f0f4ff; --el-text-dim: #94a3b8; }
body { background: var(--el-bg); margin: 0; font-family: system-ui; }
</style>
</head>
<body>
<div id="q-app">
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center">
    <q-card dark style="width:360px;background:var(--el-surface)">
      <q-card-section>
        <div class="text-h5" style="color:var(--el-primary)">openhort</div>
        <div style="color:var(--el-text-dim)">Sign in to access your machines</div>
      </q-card-section>
      <q-card-section>
        <q-input v-model="username" label="Username" dark outlined dense class="q-mb-sm" @keyup.enter="login"></q-input>
        <q-input v-model="password" label="Password" type="password" dark outlined dense @keyup.enter="login"></q-input>
        <div v-if="error" style="color:#ef4444;font-size:13px;margin-top:8px">{{ error }}</div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn label="Sign In" color="primary" :loading="loading" @click="login"></q-btn>
      </q-card-actions>
      <q-card-section v-if="hosts.length > 0">
        <div style="color:var(--el-text-dim);font-size:12px;margin-bottom:8px">Your machines:</div>
        <q-list dark dense>
          <q-item v-for="h in hosts" :key="h.host_id" clickable @click="connectHost(h)">
            <q-item-section avatar><q-icon :name="h.online ? 'desktop_windows' : 'desktop_access_disabled'" :color="h.online ? 'positive' : 'grey'"></q-icon></q-item-section>
            <q-item-section>
              <q-item-label>{{ h.display_name }}</q-item-label>
              <q-item-label caption>{{ h.online ? 'Online' : 'Offline' }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>
    </q-card>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/vue@3.5.30/dist/vue.global.prod.js"></script>
<script src="https://cdn.jsdelivr.net/npm/quasar@2.18.7/dist/quasar.umd.prod.js"></script>
<script>
const { createApp, ref } = Vue;
const app = createApp({
  setup() {
    const username = ref('');
    const password = ref('');
    const error = ref('');
    const loading = ref(false);
    const hosts = ref([]);
    const loggedIn = ref(false);

    async function login() {
      error.value = '';
      loading.value = true;
      try {
        const resp = await fetch('/api/access/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: username.value, password: password.value }),
        });
        if (!resp.ok) { error.value = (await resp.json()).detail || 'Login failed'; return; }
        loggedIn.value = true;
        await loadHosts();
      } catch (e) { error.value = 'Connection error'; }
      finally { loading.value = false; }
    }

    async function loadHosts() {
      const resp = await fetch('/api/access/hosts');
      if (resp.ok) { hosts.value = (await resp.json()).hosts; }
    }

    function connectHost(h) {
      if (!h.online) return;
      // Select host via API, then redirect to /viewer
      fetch('/api/access/select-host', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host_id: h.host_id }),
      }).then(() => { window.location.href = '/viewer'; });
    }

    // Check if already logged in
    fetch('/api/access/me').then(r => { if (r.ok) { loggedIn.value = true; loadHosts(); } });

    return { username, password, error, loading, hosts, loggedIn, login, connectHost };
  }
});
app.use(Quasar, { config: { dark: true, brand: { primary: '#3b82f6' } } });
app.mount('#q-app');
</script>
</body>
</html>"""


# ===== CLI =====


def main() -> None:  # pragma: no cover
    """Start the access proxy server."""
    import argparse

    parser = argparse.ArgumentParser(description="openhort access proxy")
    parser.add_argument("--port", type=int, default=8400)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--store", default="hort-access.json", help="JSON file or mongodb://... URI")
    parser.add_argument("--setup-user", nargs=2, metavar=("USERNAME", "PASSWORD"), help="Create a user and exit")
    parser.add_argument("--setup-host", nargs=2, metavar=("USERNAME", "DISPLAY_NAME"), help="Create a host key and exit")
    args = parser.parse_args()

    # Determine store backend
    if args.store.startswith("mongodb://"):
        from hort.access.store import MongoStore

        db_store: Store = MongoStore(args.store)
    else:
        db_store = FileStore(args.store)

    # Setup commands
    if args.setup_user:
        uname, pwd = args.setup_user
        err = validate_password_strength(pwd)
        if err:
            print(f"Error: {err}")
            sys.exit(1)
        if db_store.get_user(uname):
            print(f"User '{uname}' already exists")
            sys.exit(1)
        db_store.create_user(uname, hash_password(pwd), uname)
        print(f"Created user: {uname}")
        sys.exit(0)

    if args.setup_host:
        uname, display = args.setup_host
        if not db_store.get_user(uname):
            print(f"User '{uname}' not found")
            sys.exit(1)
        host = db_store.create_host(uname, display)
        print(f"Created host: {host.display_name}")
        print(f"Connection key: {host.connection_key}")
        print(f"Use this key to connect your openhort instance.")
        sys.exit(0)

    # Run server
    if not db_store.list_users():
        print("No users configured. Create one with:")
        print(f"  python -m hort.access.server --setup-user <username> <password>")
        sys.exit(1)

    app = create_access_app(db_store)
    for r in app.routes:
        p = getattr(r, 'path', '?')
        n = getattr(r, 'name', type(r).__name__)
        print(f"ROUTE: {p} -> {n}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
