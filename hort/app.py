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
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from hort.cert import ensure_certs
from hort.models import (
    InputEvent,
    ServerInfo,
    StatusResponse,
    StreamConfig,
    WindowListResponse,
)
from hort.input import _activate_app, handle_input
from hort.network import generate_qr_data_uri, get_lan_ip
from hort.screen import capture_window
from hort.spaces import get_spaces, switch_to_space
from hort.windows import list_windows

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

# Active WebSocket observers — tracked globally for the app instance
_active_observers: set[int] = set()
_observer_counter: int = 0


def get_observer_count() -> int:
    """Return number of currently connected observers."""
    return len(_active_observers)


def reset_observers() -> None:
    """Reset observer tracking. Used in tests."""
    global _observer_counter
    _active_observers.clear()
    _observer_counter = 0


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
    app = FastAPI(title="llming-control", version="0.1.0")
    app.state.dev_mode = is_dev
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    _register_routes(app)
    return app


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
            "background_color": "#1a1a2e",
            "theme_color": "#e94560",
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

    @app.get("/api/windows")
    async def get_windows(
        app_filter: str | None = Query(default=None),
    ) -> WindowListResponse:
        windows = list_windows(app_filter)
        app_names = sorted({w.owner_name for w in list_windows()})
        return WindowListResponse(windows=windows, app_names=app_names)

    @app.get("/api/windows/{window_id}/thumbnail")
    async def get_thumbnail(window_id: int) -> Response:
        jpeg_bytes = capture_window(window_id, max_width=400, quality=50)
        if jpeg_bytes is None:
            return Response(
                content=_generate_icon(80), media_type="image/png"
            )
        etag = hashlib.md5(jpeg_bytes).hexdigest()[:16]
        return Response(
            content=jpeg_bytes,
            media_type="image/jpeg",
            headers={"ETag": etag, "Cache-Control": "no-cache"},
        )

    @app.get("/api/status")
    async def get_status() -> StatusResponse:
        return StatusResponse(observers=len(_active_observers))

    @app.get("/api/spaces")
    async def api_spaces() -> dict[str, object]:
        spaces = get_spaces()
        return {
            "spaces": [
                {"index": s.index, "is_current": s.is_current}
                for s in spaces
            ],
            "current": next((s.index for s in spaces if s.is_current), 1),
            "count": len(spaces),
        }

    @app.post("/api/spaces/{index}")
    async def api_switch_space(index: int) -> dict[str, object]:
        ok = switch_to_space(index)
        return {"ok": ok, "target": index}

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

    @app.websocket("/ws/stream")
    async def stream_window(websocket: WebSocket) -> None:
        global _observer_counter
        await websocket.accept()
        _observer_counter += 1
        observer_id = _observer_counter
        _active_observers.add(observer_id)
        config: StreamConfig | None = None
        prev_window_id: int = 0
        try:
            while True:
                if config is None:
                    raw = await websocket.receive_text()
                    config = _parse_stream_config(raw)
                    if config is None:
                        await websocket.send_text(
                            json.dumps({"error": "Invalid config"})
                        )
                        continue

                # Raise window whenever it changes
                if config.window_id != prev_window_id:
                    _raise_window_for_config(config)
                    prev_window_id = config.window_id

                effective_max_width = _effective_max_width(config)
                frame = capture_window(
                    config.window_id, effective_max_width, config.quality
                )
                if frame is None:
                    await websocket.send_text(
                        json.dumps({"error": "Window not found or capture failed"})
                    )
                    await asyncio.sleep(1.0)
                    config = None
                    prev_window_id = 0
                    continue

                await websocket.send_bytes(frame)

                try:
                    raw = await asyncio.wait_for(
                        websocket.receive_text(), timeout=1.0 / config.fps
                    )
                    new_config = _handle_ws_message(raw, config)
                    if new_config is not None:
                        config = new_config
                except asyncio.TimeoutError:
                    pass

        except WebSocketDisconnect:
            pass
        finally:
            _active_observers.discard(observer_id)


def _raise_window_for_config(config: StreamConfig) -> None:
    """Bring the specific window to the front, switching Space if needed."""
    from hort.spaces import get_current_space_index, switch_to_space

    windows = list_windows()
    win = next((w for w in windows if w.window_id == config.window_id), None)
    if not win or not win.owner_pid:
        return
    # Auto-switch Space if the window is on a different one
    if win.space_index > 0 and win.space_index != get_current_space_index():
        switch_to_space(win.space_index)
    _activate_app(win.owner_pid, bounds=win.bounds)


def _parse_stream_config(raw: str) -> StreamConfig | None:
    """Parse a JSON string into a StreamConfig, returning None on failure."""
    try:
        data: dict[str, Any] = json.loads(raw)
        return StreamConfig(**data)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return None


def _handle_ws_message(raw: str, config: StreamConfig) -> StreamConfig | None:
    """Handle a WebSocket text message — either config update or input event.

    Returns a new StreamConfig if this was a config update, None otherwise.
    """
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None

    msg_type = data.get("type", "")

    # Input events have a type like "click", "key", "scroll", etc.
    if msg_type in ("click", "double_click", "right_click", "move", "scroll", "key"):
        try:
            event = InputEvent(**data)
            # Look up window bounds for coordinate mapping
            windows = list_windows()
            win = next(
                (w for w in windows if w.window_id == config.window_id), None
            )
            if win is not None:
                handle_input(event, win.bounds, pid=win.owner_pid)
        except (ValidationError, TypeError):
            pass
        return None

    # Otherwise treat as config update (raise handled in main loop)
    return _parse_stream_config(raw)


def _effective_max_width(config: StreamConfig) -> int:
    """Cap max_width to the client's usable screen resolution."""
    if config.screen_width > 0 and config.screen_dpr > 0:
        client_pixels = int(config.screen_width * config.screen_dpr)
        return min(config.max_width, client_pixels)
    return config.max_width


def _generate_icon(size: int) -> bytes:
    """Generate a simple app icon as PNG bytes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (26, 26, 46, 255))
    draw = ImageDraw.Draw(img)
    margin = size // 6
    # Draw a rounded rectangle (screen shape)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size // 10,
        fill=(15, 52, 96, 255),
        outline=(233, 69, 96, 255),
        width=max(2, size // 64),
    )
    # Draw a play/eye triangle in center
    cx, cy = size // 2, size // 2
    s = size // 6
    draw.polygon(
        [(cx - s, cy - s), (cx + s, cy), (cx - s, cy + s)],
        fill=(233, 69, 96, 255),
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
<title>llming-control</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #1a1a2e; color: #eee;
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; min-height: 100vh; margin: 0; padding: 20px;
    box-sizing: border-box;
}}
h1 {{ color: #e94560; margin-bottom: 8px; }}
p {{ color: #aaa; margin: 4px 0; }}
.qr {{ background: white; padding: 16px; border-radius: 12px; margin: 20px 0; }}
.qr img {{ width: 220px; height: 220px; display: block; }}
a {{ color: #0f3460; background: #e94560; padding: 12px 24px;
    border-radius: 8px; text-decoration: none; font-weight: bold;
    display: inline-block; margin-top: 12px; }}
code {{ background: #16213e; padding: 4px 10px; border-radius: 4px; color: #e94560; }}
</style>
</head>
<body>
<h1>llming-control</h1>
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

    print(f"\n  llming-control v0.1.0")
    if is_dev:
        print(f"  MODE:  DEVELOPER (hot-reload enabled)")
    print(f"  HTTP:  {server_info.http_url}")
    print(f"  HTTPS: {server_info.https_url}")
    print(f"  Scan the QR code at {server_info.http_url} to connect\n")

    asyncio.run(_run_servers(cert_path, key_path))


async def _run_servers(cert_path: Path, key_path: Path) -> None:  # pragma: no cover
    """Run both HTTP and HTTPS uvicorn servers concurrently."""
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
