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
import json
import logging
import os
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
            return await asyncio.wait_for(future, timeout=30.0)
        finally:
            self._pending.pop(req_id, None)

    async def send_raw(self, msg: str) -> None:
        """Queue a raw JSON message to send through the tunnel."""
        await self._send_queue.put(msg)

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
            except (WebSocketDisconnect, Exception):
                pass

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
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("ACCESS_SESSION_SECRET") or secrets.token_hex(32),
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

    @app.get("/api/access/token/login")
    async def token_login(request: Request) -> Response:
        """Login via a token generated on the host.

        Flow:
        1. User scans QR code containing this URL + token + host_id
        2. Access server applies rate limiting + artificial delay
        3. Access server forwards token to the host via tunnel
        4. Host verifies the token against its local TokenStore
        5. If valid, access server creates a session
        """
        token = request.query_params.get("token", "")
        host_id = request.query_params.get("host", "")
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

            body = json.loads(resp.get("body", "{}"))
            if not body.get("valid"):
                raise HTTPException(401, "Invalid or expired token")
        except (ConnectionError, asyncio.TimeoutError):
            raise HTTPException(502, "Host not responding")

        # Token valid — find the host owner and create session
        for h_record in store.get_hosts_for_user(""):
            pass  # need to find owner from host_id
        # Look up host record to find owner
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
        # Redirect to the host's proxy viewer
        return RedirectResponse(f"/proxy/{host_id}/viewer", status_code=302)

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
        tunnel = HostTunnel(host_record.host_id, host_record.display_name, websocket)
        _tunnels[host_record.host_id] = tunnel
        logger.info("Host connected: %s (%s)", host_record.display_name, host_record.host_id)

        try:
            await tunnel.run()
        finally:
            _tunnels.pop(host_record.host_id, None)
            logger.info("Host disconnected: %s", host_record.display_name)

    # ===== WebSocket proxy =====

    @app.websocket("/proxy/{host_id}/{path:path}")
    async def ws_proxy(websocket: WebSocket, host_id: str, path: str) -> None:
        """Proxy WebSocket connections to the host."""
        tunnel = _tunnels.get(host_id)
        if tunnel is None:
            await websocket.close(code=4004, reason="Host not connected")
            return

        await websocket.accept()

        # Tell the host to open a WS connection
        ws_id = secrets.token_hex(8)
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

    # ===== HTTP proxy =====

    @app.api_route("/proxy/{host_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def http_proxy(request: Request, host_id: str, path: str) -> Response:
        """Proxy HTTP requests to the host."""
        # Check auth
        username = request.session.get("username")
        if not username:
            raise HTTPException(401, "Not authenticated")

        tunnel = _tunnels.get(host_id)
        if tunnel is None:
            raise HTTPException(502, "Host not connected")

        body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            resp = await tunnel.proxy_request(
                request.method, f"/{path}", headers, body
            )
        except (ConnectionError, asyncio.TimeoutError):
            raise HTTPException(502, "Host not responding")

        return Response(
            content=resp.get("body", "").encode("latin-1"),
            status_code=resp.get("status", 200),
            headers=resp.get("headers", {}),
        )

    # ===== Landing page =====

    @app.get("/")
    async def landing() -> HTMLResponse:
        return HTMLResponse(_landing_html())


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
<script src="https://cdn.jsdelivr.net/npm/vue@3.5.30/dist/vue.global.prod.js"></script>
<script src="https://cdn.jsdelivr.net/npm/quasar@2.18.7/dist/quasar.umd.prod.js"></script>
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
      window.location.href = '/proxy/' + h.host_id + '/viewer';
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
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
