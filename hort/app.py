"""FastAPI application: routes, WebSocket streaming, and server startup."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from hort.cert import ensure_certs
from hort.models import ServerInfo
from hort.network import generate_qr_data_uri, get_lan_ip

STATIC_DIR = Path(__file__).parent / "static"
CERTS_DIR = Path(__file__).parent.parent / "certs"
_ENV_FILE = Path(__file__).parent.parent / ".env"
HTTP_PORT = 8940
HTTPS_PORT = 8950

# Load .env if present (before reading DEV_MODE)
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

DEV_MODE = os.environ.get("LLMING_DEV", "0") == "1"


def _file_hash(path: Path) -> str:
    """Compute a short content hash for cache busting."""
    if not path.exists():
        return "0"
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:12]


def _static_hash() -> str:
    """Compute a combined hash of all static files for cache busting."""
    index_path = STATIC_DIR / "index.html"
    return _file_hash(index_path)


def create_app(*, dev_mode: bool | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    is_dev = dev_mode if dev_mode is not None else DEV_MODE
    app = FastAPI(title="openhort", version="0.1.0")
    app.state.dev_mode = is_dev
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    _register_targets()
    _register_routes(app)

    @app.on_event("startup")
    async def _start_target_scanner() -> None:
        """Periodically re-scan for Docker containers in the background."""
        async def _scan_loop() -> None:
            while True:
                await asyncio.sleep(10)
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, _refresh_docker_targets)
                except Exception:  # pragma: no cover
                    pass

        asyncio.create_task(_scan_loop())

    return app


def _refresh_docker_targets() -> None:
    """Re-scan for Docker Linux containers and update the target registry."""
    from hort.targets import TargetRegistry

    registry = TargetRegistry.get()

    # Find currently running containers
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", "ancestor=openhort-linux-desktop"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return

        running = set()
        for name in result.stdout.strip().splitlines():
            if not name:
                continue
            running.add(f"docker-{name}")

        # Add new containers
        for name in result.stdout.strip().splitlines():
            if not name:
                continue
            target_id = f"docker-{name}"
            if registry.get_provider(target_id) is None:
                try:
                    from hort.extensions.core.linux_windows.provider import (
                        LinuxWindowsExtension,
                    )
                    from hort.targets import TargetInfo

                    ext = LinuxWindowsExtension()
                    ext.activate({"container_name": name})
                    registry.register(
                        target_id,
                        TargetInfo(id=target_id, name=f"Linux ({name})", provider_type="linux-docker"),
                        ext,
                    )
                except ImportError:
                    pass

        # Remove stopped containers
        for info in registry.list_targets():
            if info.id.startswith("docker-") and info.id not in running:
                registry.remove(info.id)

    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _register_targets() -> None:
    """Register platform targets available on this machine."""
    from hort.targets import TargetInfo, TargetRegistry

    registry = TargetRegistry.get()

    # Register local macOS target (only on macOS)
    if sys.platform == "darwin":
        try:
            from hort.extensions.core.macos_windows.provider import (
                MacOSWindowsExtension,
            )

            registry.register(
                "local-macos",
                TargetInfo(id="local-macos", name="This Mac", provider_type="macos"),
                MacOSWindowsExtension(),
            )
        except ImportError:
            pass  # Quartz not available

    # Docker containers are discovered by the background scanner (_refresh_docker_targets)
    # which runs every 10 seconds — no need to block startup
    _refresh_docker_targets()


def _register_routes(app: FastAPI) -> None:
    """Register all HTTP and WebSocket routes."""

    @app.get("/", response_class=HTMLResponse)
    async def landing_page() -> str:
        lan_ip = get_lan_ip()
        server_info = ServerInfo(
            lan_ip=lan_ip, http_port=HTTP_PORT, https_port=HTTPS_PORT
        )
        qr_data_uri = generate_qr_data_uri(server_info.https_url)
        return _render_landing(server_info, qr_data_uri, _static_hash())

    @app.get("/viewer", response_class=HTMLResponse)
    async def viewer_page() -> HTMLResponse:
        index_path = STATIC_DIR / "index.html"
        content = index_path.read_text()
        h = _static_hash()
        dev_script = _dev_reload_script() if app.state.dev_mode else ""
        content = content.replace("</body>", f"{dev_script}</body>")
        # Cache-bust CDN links won't change, but our own assets need hashing
        resp = HTMLResponse(content=content)
        resp.headers["ETag"] = h
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/api/hash")
    async def get_hash() -> dict[str, str]:
        return {"hash": _static_hash(), "dev": str(app.state.dev_mode)}

    @app.get("/manifest.json")
    async def manifest() -> Response:
        data = {
            "name": "hort – Remote Mac Viewer",
            "short_name": "hort",
            "start_url": "/viewer",
            "display": "fullscreen",
            "orientation": "any",
            "background_color": "#0a0e1a",
            "theme_color": "#3b82f6",
            "icons": [
                {"src": "/api/icon/192", "sizes": "192x192", "type": "image/png"},
                {"src": "/api/icon/512", "sizes": "512x512", "type": "image/png"},
            ],
        }
        return Response(
            content=json.dumps(data),
            media_type="application/manifest+json",
        )

    @app.get("/api/icon/{size}")
    async def app_icon(size: int) -> Response:
        return Response(
            content=_generate_icon(min(size, 1024)),
            media_type="image/png",
        )

    @app.get("/sw.js")
    async def service_worker() -> Response:
        return Response(
            content=_SERVICE_WORKER_JS,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.post("/api/session")
    async def create_session() -> dict[str, str]:
        """Create a new viewer session and return its ID."""
        from hort.session import HortRegistry, HortSessionEntry

        registry = HortRegistry.get()
        import secrets

        session_id = secrets.token_urlsafe(24)
        entry = HortSessionEntry(user_id="viewer")
        registry.register(session_id, entry)
        return {"session_id": session_id}

    @app.websocket("/ws/control/{session_id}")
    async def control_ws(websocket: WebSocket, session_id: str) -> None:
        """Control channel — all JSON commands flow through here."""
        from llming_com import run_websocket_session

        from hort.controller import HortController
        from hort.session import HortRegistry, HortSessionEntry

        registry = HortRegistry.get()

        async def on_connect(
            entry: object, ws: WebSocket
        ) -> None:
            assert isinstance(entry, HortSessionEntry)
            controller = HortController(session_id)
            controller.set_websocket(ws)
            controller.set_session_entry(entry)
            entry.controller = controller
            await controller.send({"type": "connected", "version": "0.1.0"})

        async def on_message(entry: object, msg: dict[str, Any]) -> None:
            assert isinstance(entry, HortSessionEntry)
            if entry.controller:
                await entry.controller.handle_message(msg)

        async def on_disconnect(sid: str, entry: object) -> None:
            assert isinstance(entry, HortSessionEntry)
            if entry.controller:
                await entry.controller.cleanup()

        await run_websocket_session(
            websocket,
            session_id,
            registry,
            on_connect=on_connect,
            on_message=on_message,
            on_disconnect=on_disconnect,
            log_prefix="CTRL",
        )

    @app.websocket("/ws/stream/{session_id}")
    async def session_stream(websocket: WebSocket, session_id: str) -> None:
        """Binary stream channel — JPEG frames for a window."""
        from hort.session import HortRegistry
        from hort.stream import run_stream

        registry: HortRegistry = HortRegistry.get()  # type: ignore[assignment]
        await run_stream(websocket, session_id, registry)

    @app.websocket("/ws/terminal/{terminal_id}")
    async def terminal_ws(websocket: WebSocket, terminal_id: str) -> None:
        """Terminal I/O — bridges browser WS to the persistent termd daemon."""
        from hort.termd_client import handle_terminal_ws

        await handle_terminal_ws(websocket, terminal_id)

    @app.websocket("/ws/devreload")
    async def dev_reload(websocket: WebSocket) -> None:
        """Watch static files and notify client to reload on change."""
        await websocket.accept()
        last_hash = _static_hash()
        try:
            while True:
                await asyncio.sleep(0.5)
                current_hash = _static_hash()
                if current_hash != last_hash:
                    last_hash = current_hash
                    await websocket.send_text(
                        json.dumps({"type": "reload", "hash": current_hash})
                    )
        except WebSocketDisconnect:
            pass

def _generate_icon(size: int) -> bytes:
    """Generate a simple app icon as PNG bytes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (10, 14, 26, 255))
    draw = ImageDraw.Draw(img)
    margin = size // 6
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size // 10,
        fill=(30, 58, 95, 255),
        outline=(59, 130, 246, 255),
        width=max(2, size // 64),
    )
    cx, cy = size // 2, size // 2
    s = size // 6
    draw.polygon(
        [(cx - s, cy - s), (cx + s, cy), (cx - s, cy + s)],
        fill=(59, 130, 246, 255),
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_SERVICE_WORKER_JS = """\
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.url.startsWith('blob:') || e.request.url.includes('/ws/')) return;
  e.respondWith(fetch(e.request));
});
"""


def _dev_reload_script() -> str:
    """Return a script tag that auto-reloads the page when static files change."""
    return """<script>
(function(){
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    function connect() {
        const ws = new WebSocket(proto + '://' + location.host + '/ws/devreload');
        ws.onmessage = function(e) {
            const msg = JSON.parse(e.data);
            if (msg.type === 'reload') { console.log('[dev] reloading...'); location.reload(); }
        };
        ws.onclose = function() { setTimeout(connect, 1000); };
    }
    connect();
    console.log('[dev] hot-reload enabled');
})();
</script>"""


def _render_landing(server_info: ServerInfo, qr_data_uri: str, static_hash: str = "") -> str:
    """Render the landing page HTML with QR code."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>openhort</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #0a0e1a; color: #f0f4ff;
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; min-height: 100vh; margin: 0; padding: 20px;
    box-sizing: border-box;
}}
h1 {{ color: #3b82f6; margin-bottom: 8px; }}
p {{ color: #aaa; margin: 4px 0; }}
.qr {{ background: white; padding: 16px; border-radius: 12px; margin: 20px 0; }}
.qr img {{ width: 220px; height: 220px; display: block; }}
a {{ color: #fff; background: #3b82f6; padding: 12px 24px;
    border-radius: 8px; text-decoration: none; font-weight: bold;
    display: inline-block; margin-top: 12px; }}
code {{ background: #111827; padding: 4px 10px; border-radius: 4px; color: #60a5fa; }}
</style>
</head>
<body>
<h1>openhort</h1>
<p>Scan the QR code with your phone to connect</p>
<div class="qr"><img src="{qr_data_uri}" alt="QR Code"></div>
<p>Or open manually:</p>
<p><code>{server_info.https_url}</code></p>
<a href="/viewer?v={static_hash}">Open Viewer</a>
<p style="margin-top:20px;font-size:12px;color:#666">
  HTTP: {server_info.http_url} &middot; HTTPS: {server_info.https_url}
</p>
<p style="font-size:11px;color:#444">v0.1.0 &middot; build {static_hash}</p>
</body>
</html>"""


app = create_app()


def main() -> None:  # pragma: no cover
    """Entry point: start HTTP and HTTPS servers."""
    global app

    is_dev = "--dev" in sys.argv or DEV_MODE
    if is_dev:
        os.environ["LLMING_DEV"] = "1"
    app = create_app(dev_mode=is_dev)

    lan_ip = get_lan_ip()
    cert_path, key_path = ensure_certs(CERTS_DIR, lan_ip=lan_ip)

    server_info = ServerInfo(
        lan_ip=lan_ip, http_port=HTTP_PORT, https_port=HTTPS_PORT
    )

    print(f"\n  openhort v0.1.0")
    if is_dev:
        print(f"  MODE:  DEVELOPER (auto-reload enabled)")
    print(f"  HTTP:  {server_info.http_url}")
    print(f"  HTTPS: {server_info.https_url}")
    print(f"  Scan the QR code at {server_info.http_url} to connect\n")

    if is_dev:
        _run_dev(cert_path, key_path)
    else:
        asyncio.run(_run_servers(cert_path, key_path))


def _run_dev(cert_path: Path, key_path: Path) -> None:  # pragma: no cover
    """Run with uvicorn --reload for auto-restart on Python file changes.

    Runs a single HTTP server on port 8940. HTTPS on port 8950 is handled
    by the nginx proxy in ``tools/local-https/`` (run it once with
    ``docker compose up -d``).  The proxy shows a "Server restarting..."
    page during reloads instead of a connection error.
    """
    import subprocess

    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "hort.app:app",
        "--host", "0.0.0.0",
        "--port", str(HTTP_PORT),
        "--reload",
        "--reload-dir", str(Path(__file__).parent),
        "--log-level", "info",
    ])


async def _run_servers(cert_path: Path, key_path: Path) -> None:  # pragma: no cover
    """Run both HTTP and HTTPS uvicorn servers concurrently (production)."""
    http_config = uvicorn.Config(
        app, host="0.0.0.0", port=HTTP_PORT, log_level="info"
    )
    https_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=HTTPS_PORT,
        log_level="info",
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )
    http_server = uvicorn.Server(http_config)
    https_server = uvicorn.Server(https_config)

    await asyncio.gather(http_server.serve(), https_server.serve())


if __name__ == "__main__":  # pragma: no cover
    main()
