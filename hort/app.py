"""FastAPI application: routes, WebSocket streaming, and server startup."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ===== Rotating log file — captures startup, shutdown, and deadlocks =====
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_log_handler = RotatingFileHandler(
    str(_LOG_DIR / "openhort.log"),
    maxBytes=5 * 1024 * 1024,  # 5 MB per file
    backupCount=3,
)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s"
))
# Attach to 'hort' namespace logger (not root — uvicorn may clear root handlers)
_hort_logger = logging.getLogger("hort")
# Clear stale handlers from previous reloads, then add fresh ones
_hort_logger.handlers = [h for h in _hort_logger.handlers if not isinstance(h, RotatingFileHandler)]
_hort_logger.addHandler(_log_handler)
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
_hort_logger.addHandler(_stream_handler)
_hort_logger.setLevel(logging.DEBUG)
_hort_logger.propagate = False  # don't double-log through root
logging.getLogger().setLevel(logging.INFO)

logger = logging.getLogger("hort.app")

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from hort.cert import ensure_certs
from hort.models import ServerInfo
from hort.network import generate_qr_data_uri, get_lan_ip

STATIC_DIR = Path(__file__).parent / "static"
CERTS_DIR = Path(__file__).parent.parent / "certs"
_ENV_FILE = Path(__file__).parent.parent / ".env"

# Load .env if present (before reading any config)
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

HTTP_PORT = int(os.environ.get("HORT_HTTP_PORT", "8940"))
HTTPS_PORT = int(os.environ.get("HORT_HTTPS_PORT", "8950"))
DEV_MODE = os.environ.get("LLMING_DEV", "0") == "1"


def _file_hash(path: Path) -> str:
    """Compute a short content hash for cache busting."""
    if not path.exists():
        return "0"
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:12]


def _static_hash() -> str:
    """Compute a combined hash of static files + extension scripts for cache busting."""
    h = hashlib.sha256()
    # Main UI
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        h.update(index_path.read_bytes())
    # hort-ext.js
    ext_js = STATIC_DIR / "vendor" / "hort-ext.js"
    if ext_js.exists():
        h.update(ext_js.read_bytes())
    # Extension assets (js, css, html)
    ext_dir = Path(__file__).parent / "extensions" / "core"
    if ext_dir.exists():
        for f in sorted(ext_dir.rglob("*")):
            if f.suffix in (".js", ".css", ".html") and f.is_file():
                h.update(f.read_bytes())
    # Vendor assets (hort-ext.js already covered above, catch css changes)
    vendor_dir = STATIC_DIR / "vendor"
    if vendor_dir.exists():
        for f in sorted(vendor_dir.iterdir()):
            if f.suffix in (".js", ".css") and f.is_file() and f.name != "hort-ext.js":
                h.update(f.read_bytes())
    return h.hexdigest()[:12]


def create_app(*, dev_mode: bool | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    logger.info("Creating app (dev_mode=%s, pid=%d)", dev_mode, os.getpid())
    is_dev = dev_mode if dev_mode is not None else DEV_MODE
    app = FastAPI(title="openhort", version="0.1.0")
    app.state.dev_mode = is_dev
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Mount extension static directories
    _ext_dir = Path(__file__).parent / "extensions" / "core"
    if _ext_dir.exists():
        for ext_path in _ext_dir.iterdir():
            static_dir = ext_path / "static"
            if static_dir.is_dir():
                app.mount(
                    f"/ext/{ext_path.name}/static",
                    StaticFiles(directory=str(static_dir)),
                    name=f"ext-{ext_path.name}",
                )

    # Mount documentation site (pre-built mkdocs HTML)
    _docs_site = Path(__file__).parent.parent / "docs" / "_site"
    if _docs_site.is_dir():
        app.mount(
            "/guide",
            StaticFiles(directory=str(_docs_site), html=True),
            name="guide",
        )
        logger.info("Documentation mounted at /guide")

    _register_targets()
    _register_routes(app)

    # Plugins — discovery and route registration only (no loading yet).
    # Actual loading + scheduling + connectors happen in the startup event.
    from hort.plugins import load_plugins_sync, setup_plugins, start_plugins, stop_plugins

    plugin_registry = setup_plugins(app)

    @app.on_event("startup")
    async def _on_startup() -> None:
        load_plugins_sync(plugin_registry)
        await start_plugins(plugin_registry)
        logger.info("App startup complete (pid=%d)", os.getpid())

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        logger.info("App shutdown initiated (pid=%d)", os.getpid())
        await stop_plugins(plugin_registry)

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

    @app.on_event("startup")
    async def _start_cloud_connector() -> None:
        """Auto-start cloud tunnel and create temporary token if enabled."""
        from hort.config import get_store

        cloud = get_store().get("connector.cloud")
        if cloud.get("enabled") and cloud.get("server") and cloud.get("key"):
            _apply_cloud_config(cloud)
        # Always create tokens if cloud is configured (even if tunnel not started yet)
        if cloud.get("server") and cloud.get("host_id"):
            _create_startup_tokens(app)

    @app.post("/api/connectors/cloud/token")
    async def create_cloud_token(request: Request) -> Response:
        """Create or regenerate a cloud access token."""
        data = await request.json()
        permanent = data.get("permanent", False)
        from hort.access.tokens import TokenStore

        store = TokenStore()
        if permanent:
            token = store.create_permanent("Cloud Access Key")
            app.state.cloud_tokens["permanent"] = token
        else:
            # Create a new temp token (old ones stay valid until they expire)
            token = store.create_temporary("Cloud QR Session", duration_seconds=86400)
            app.state.cloud_tokens["temporary"] = token
            _TEMP_TOKEN_FILE.write_text(token)
        return Response(
            content=json.dumps({"ok": True, "token": token, "permanent": permanent}),
            media_type="application/json",
        )

    @app.get("/api/qr")
    async def generate_qr(request: Request) -> Response:
        """Generate a QR code data URI for any URL."""
        url = request.query_params.get("url", "")
        if not url:
            return Response(
                content=json.dumps({"qr": ""}), media_type="application/json"
            )
        qr_data_uri = generate_qr_data_uri(url)
        return Response(
            content=json.dumps({"qr": qr_data_uri}), media_type="application/json"
        )

    return app


_TEMP_TOKEN_FILE = Path("~/.hort/current-temp-token").expanduser()


def _create_startup_tokens(app: FastAPI) -> None:  # pragma: no cover
    """Reuse existing temp token if still valid, otherwise create a new one."""
    from hort.access.tokens import TokenStore

    store = TokenStore()
    temp_token = ""

    # Try to reuse persisted temp token
    if _TEMP_TOKEN_FILE.exists():
        saved = _TEMP_TOKEN_FILE.read_text().strip()
        if saved and store.verify(saved):
            temp_token = saved
            logger.info("Reusing existing temp token (still valid)")

    # Create new one only if no valid token
    if not temp_token:
        temp_token = store.create_temporary("Cloud Session", duration_seconds=86400)
        _TEMP_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TEMP_TOKEN_FILE.write_text(temp_token)
        logger.info("Created new temp token (24h)")

    # Check if a permanent token exists
    has_perm = any(
        t["permanent"] and t["label"] == "Cloud Access Key"
        for t in store.list_tokens()
    )
    app.state.cloud_tokens = {
        "temporary": temp_token,
        "has_permanent": has_perm,
    }


def _apply_cloud_config(config: dict[str, Any]) -> None:  # pragma: no cover
    """Start or stop the cloud tunnel based on config."""
    import signal
    import subprocess

    active_file = Path("/tmp/hort-tunnel.active")
    pid_file = Path("/tmp/hort-tunnel.pid")

    # Kill existing tunnel if running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            logger.info("Stopped cloud tunnel (pid %d)", pid)
        except (ProcessLookupError, ValueError, OSError):
            pass
        pid_file.unlink(missing_ok=True)
        active_file.unlink(missing_ok=True)

    # Start new tunnel if enabled
    if config.get("enabled") and config.get("server") and config.get("key"):
        logger.info("Starting cloud tunnel to %s", config["server"])
        proc = subprocess.Popen(
            [sys.executable, "-m", "hort.access.tunnel_client",
             f"--server={config['server']}", f"--key={config['key']}",
             "--local=http://localhost:8940"],
            stdout=open("/tmp/hort-tunnel.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        pid_file.write_text(str(proc.pid))
    else:
        logger.info("Cloud tunnel disabled")


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

    # Register native Linux target (only on Linux with X11)
    if sys.platform == "linux":
        try:
            from hort.extensions.core.linux_native.provider import (
                LinuxNativeExtension,
            )

            ext = LinuxNativeExtension()
            ext.activate({})
            registry.register(
                "local-linux",
                TargetInfo(id="local-linux", name="This Linux", provider_type="linux"),
                ext,
            )
        except ImportError:
            pass

    # Register native Windows target (only on Windows)
    if sys.platform == "win32":
        try:
            from hort.extensions.core.windows_native.provider import (
                WindowsNativeExtension,
            )

            ext = WindowsNativeExtension()
            ext.activate({})
            registry.register(
                "local-windows",
                TargetInfo(id="local-windows", name="This PC", provider_type="windows"),
                ext,
            )
        except ImportError:
            pass

    # Docker containers are discovered by the background scanner (_refresh_docker_targets)
    # which runs every 10 seconds — no need to block startup
    _refresh_docker_targets()


def _register_routes(app: FastAPI) -> None:
    """Register all HTTP and WebSocket routes."""
    # Hort Map API
    from hort.hortmap.routes import create_hortmap_router
    app.include_router(create_hortmap_router())

    @app.get("/", response_class=HTMLResponse)
    async def root_page() -> HTMLResponse:
        """Serve the viewer as the root page."""
        return await viewer_page()

    @app.get("/p2p", response_class=HTMLResponse)
    async def p2p_viewer_page() -> HTMLResponse:
        """Serve the P2P viewer (works in Telegram Mini App and standalone browser)."""
        path = Path(__file__).parent / "extensions" / "core" / "peer2peer" / "static" / "viewer.html"
        return HTMLResponse(content=path.read_text())

    @app.get("/hortmap", response_class=HTMLResponse)
    async def hortmap_page() -> HTMLResponse:
        """Serve the Hort Map editor."""
        path = STATIC_DIR / "hortmap.html"
        content = path.read_text()
        dev_script = _dev_reload_script() if app.state.dev_mode else ""
        content = content.replace("</body>", f"{dev_script}</body>")
        return HTMLResponse(content=content)

    @app.get("/view/{path:path}", response_class=HTMLResponse)
    async def view_deep_link(path: str) -> HTMLResponse:
        """Deep-link into the viewer.

        URL scheme: /view/{target}/{window}?codec=vp8&fps=15&quality=70&zoom=2
        Examples:
          /view/local/desktop           → local machine full desktop
          /view/local/desktop?codec=vp8 → VP8 video stream
          /view/local/42?zoom=3         → window #42 at 3x zoom
          /view/docker-linux/desktop    → Linux container desktop
        """
        index_path = STATIC_DIR / "index.html"
        content = index_path.read_text()
        dev_script = _dev_reload_script() if app.state.dev_mode else ""
        content = content.replace("</body>", f"{dev_script}</body>")
        # Inject <base href="/"> so relative script paths resolve correctly
        content = content.replace("<head>", '<head><base href="/">', 1)
        return HTMLResponse(content=content)

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

    @app.get("/api/debug/memory")
    async def debug_memory() -> dict[str, Any]:
        """Memory diagnostics — find what's using RAM."""
        import gc
        import os
        import sys

        gc.collect()

        # Process RSS
        import resource
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On macOS ru_maxrss is in bytes, on Linux in KB
        rss_mb = rss_bytes / (1024 * 1024) if sys.platform == "darwin" else rss_bytes / 1024

        # Count objects by type (top 20)
        type_counts: dict[str, int] = {}
        type_sizes: dict[str, int] = {}
        for obj in gc.get_objects():
            t = type(obj).__name__
            type_counts[t] = type_counts.get(t, 0) + 1
            try:
                type_sizes[t] = type_sizes.get(t, 0) + sys.getsizeof(obj)
            except Exception:
                pass

        top_counts = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        top_sizes = sorted(type_sizes.items(), key=lambda x: x[1], reverse=True)[:20]

        # asyncio tasks
        import asyncio
        tasks = [t for t in asyncio.all_tasks() if not t.done()]

        return {
            "rss_mb": round(rss_mb, 1),
            "gc_objects": len(gc.get_objects()),
            "gc_garbage": len(gc.garbage),
            "asyncio_tasks": len(tasks),
            "task_names": [t.get_name() for t in tasks[:20]],
            "top_object_counts": top_counts,
            "top_object_sizes_mb": [(t, round(s / 1024 / 1024, 2)) for t, s in top_sizes],
        }

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

    @app.get("/api/connectors")
    async def get_connectors() -> Response:
        """Return active connectors (LAN, cloud proxy). Only for local access."""
        lan_ip = get_lan_ip()
        server_info = ServerInfo(
            lan_ip=lan_ip, http_port=HTTP_PORT, https_port=HTTPS_PORT
        )
        qr_data_uri = generate_qr_data_uri(server_info.https_url)

        # Check tunnel status — file format: server_url\nhost_id
        tunnel_active = Path("/tmp/hort-tunnel.active").exists()
        tunnel_server = ""
        tunnel_host_id = ""
        if tunnel_active:  # pragma: no cover
            try:
                lines = Path("/tmp/hort-tunnel.active").read_text().strip().split("\n")
                tunnel_server = lines[0] if lines else ""
                tunnel_host_id = lines[1] if len(lines) > 1 else ""
            except OSError:
                pass

        # Fallback: read host_id from config if not in tunnel file
        if not tunnel_host_id:  # pragma: no cover
            from hort.config import get_store

            cloud_cfg = get_store().get("connector.cloud")
            tunnel_host_id = cloud_cfg.get("host_id", "")

        # Cloud tokens — read from app state
        cloud_tokens: dict[str, Any] = {}
        if hasattr(app.state, "cloud_tokens"):  # pragma: no cover
            cloud_tokens = app.state.cloud_tokens

        # Messaging connectors (Telegram, etc.) from plugin registry
        messaging: dict[str, Any] = {}
        if hasattr(app.state, "plugin_registry"):  # pragma: no cover
            from hort.ext.connectors import ConnectorBase

            for name, inst in app.state.plugin_registry._instances.items():
                if isinstance(inst, ConnectorBase):
                    status = inst.get_status() if hasattr(inst, "get_status") else {}
                    messaging[inst.connector_id] = {
                        "active": status.get("active", False),
                        "plugin_id": name,
                        **status,
                    }

        return Response(
            content=json.dumps({
                "lan": {
                    "active": True,
                    "ip": lan_ip,
                    "http_url": server_info.http_url,
                    "https_url": server_info.https_url,
                    "qr": qr_data_uri,
                },
                "cloud": {
                    "active": tunnel_active,
                    "server_url": tunnel_server,
                    "host_id": tunnel_host_id,
                    "tokens": cloud_tokens,
                },
                "messaging": messaging,
            }),
            media_type="application/json",
        )

    @app.get("/api/config/{plugin_id:path}")
    async def get_config(plugin_id: str) -> Response:
        """Get system config by ID (connectors, etc). NOT for plugin data — use /api/plugins/{id}/store."""
        from hort.config import get_store

        config = get_store().get(plugin_id)
        return Response(content=json.dumps(config), media_type="application/json")

    @app.post("/api/config/{plugin_id:path}")
    async def update_config(plugin_id: str, request: Request) -> Response:
        """Update config for a plugin by its unique ID (merge)."""
        from hort.config import get_store

        data = await request.json()
        merged = get_store().update(plugin_id, data)

        # React to cloud connector enable/disable
        if plugin_id == "connector.cloud":
            _apply_cloud_config(merged)

        return Response(
            content=json.dumps({"ok": True, "config": merged}),
            media_type="application/json",
        )

    @app.post("/api/session")
    async def create_session(request: Request) -> dict[str, Any]:
        """Create a new viewer session and return its ID.

        Detects if the request is local or proxied so the UI knows
        whether to show connector controls.
        """
        from hort.session import HortRegistry, HortSessionEntry

        registry = HortRegistry.get()
        import secrets

        session_id = secrets.token_urlsafe(24)
        # Detect if accessed locally or through the proxy
        host_header = request.headers.get("host", "")
        is_local = (
            "localhost" in host_header
            or host_header.startswith("127.")
            or host_header.split(":")[0].count(".") == 3  # IP address
        )
        entry = HortSessionEntry(user_id="viewer")
        registry.register(session_id, entry)
        return {"session_id": session_id, "is_local": is_local}

    # --- P2P WebRTC signaling ---

    # Active P2P sessions from HTTP mode (LAN)
    _p2p_sessions: dict[str, tuple[Any, Any]] = {}  # session_id -> (peer, proxy)
    from hort.peer2peer.relay_listener import ReconnectTokenStore
    _http_reconnect_tokens = ReconnectTokenStore()

    @app.post("/api/p2p/offer")
    async def p2p_offer(request: Request) -> dict[str, Any]:
        """Accept a WebRTC SDP offer from a browser and return the answer."""
        import secrets as _secrets

        from hort.peer2peer.dc_proxy import DataChannelProxy
        from hort.peer2peer.webrtc import WebRTCPeer

        body = await request.json()
        sdp = body.get("sdp", "")
        if not sdp:
            return {"error": "sdp required"}

        session_id = f"http-{_secrets.token_hex(4)}"
        proxy = DataChannelProxy(peer=None)  # type: ignore[arg-type]

        async def on_message(data: bytes | str) -> None:
            await proxy.handle_message(data)

        async def on_state_change(state: str) -> None:
            if state in ("failed", "closed"):
                entry = _p2p_sessions.pop(session_id, None)
                if entry:
                    await entry[1].stop()

        peer = WebRTCPeer(on_message=on_message, on_state_change=on_state_change)
        proxy._peer = peer
        proxy._reconnect_store = _http_reconnect_tokens

        answer_sdp = await peer.accept_offer(sdp)
        await proxy.start()

        _p2p_sessions[session_id] = (peer, proxy)

        return {"sdp": answer_sdp, "type": "answer", "session_id": session_id}

    @app.get("/api/p2p/status")
    async def p2p_status() -> dict[str, Any]:
        """Get P2P connection status."""
        relay_sessions = 0
        if getattr(app.state, "plugin_registry", None):
            plugin = app.state.plugin_registry.get_instance("peer2peer")
            if plugin and getattr(plugin, "_relay_listener", None):
                relay_sessions = plugin._relay_listener.active_sessions
        return {
            "http_sessions": len(_p2p_sessions),
            "relay_sessions": relay_sessions,
            "total": len(_p2p_sessions) + relay_sessions,
        }

    @app.post("/api/p2p/connect")
    async def p2p_connect() -> dict[str, Any]:
        """Generate a one-time P2P connection URL."""
        if not hasattr(app.state, "plugin_registry"):
            return {"error": "plugins not loaded"}
        plugin = app.state.plugin_registry.get_instance("peer2peer")
        if not plugin or not hasattr(plugin, "_relay_poller") or not plugin._relay_poller:
            return {"error": "P2P relay not running"}
        poller = plugin._relay_poller
        token = poller.tokens.generate()
        room = plugin._room_id
        url = f"https://openhort.ai/p2p/viewer.html?signal=ws&room={room}&token={token}"

        # Listen on relay WebSocket temporarily so the viewer's SDP offer gets answered
        asyncio.create_task(poller.listen_for_sdp_once(timeout=60.0))

        return {"url": url, "token": token, "room": room, "expires_in": 60}

    @app.post("/api/p2p/pair")
    async def p2p_pair(request: Request) -> dict[str, Any]:
        """Generate a permanent device pairing link (deep link for mobile apps)."""
        if not hasattr(app.state, "plugin_registry"):
            return {"error": "plugins not loaded"}
        plugin = app.state.plugin_registry.get_instance("peer2peer")
        if not plugin or not hasattr(plugin, "_device_store") or not plugin._device_store:
            return {"error": "Device store not available"}
        if not hasattr(plugin, "_relay_poller") or not plugin._relay_poller:
            return {"error": "P2P relay not running"}

        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        label = body.get("label", "Device")

        token = plugin._device_store.create(label=label)
        room = plugin._room_id
        relay = plugin._relay_url

        from urllib.parse import quote
        deep_link = f"openhort://pair?token={quote(token, safe='')}&room={quote(room, safe='')}&relay={quote(relay, safe='')}"
        return {"deep_link": deep_link, "token": token, "room": room, "relay": relay}

    @app.get("/api/p2p/devices")
    async def p2p_devices_list() -> dict[str, Any]:
        """List all paired devices."""
        if not hasattr(app.state, "plugin_registry"):
            return {"devices": []}
        plugin = app.state.plugin_registry.get_instance("peer2peer")
        if not plugin or not hasattr(plugin, "_device_store") or not plugin._device_store:
            return {"devices": []}
        return {"devices": plugin._device_store.list_devices()}

    @app.delete("/api/p2p/devices")
    async def p2p_device_revoke(request: Request) -> dict[str, Any]:
        """Revoke a paired device by token_hash."""
        if not hasattr(app.state, "plugin_registry"):
            return {"error": "plugins not loaded"}
        plugin = app.state.plugin_registry.get_instance("peer2peer")
        if not plugin or not hasattr(plugin, "_device_store") or not plugin._device_store:
            return {"error": "Device store not available"}
        body = await request.json()
        token_hash = body.get("token_hash", "")
        if not token_hash:
            return {"error": "token_hash required"}
        ok = plugin._device_store.revoke(token_hash)
        return {"ok": ok}

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

    # ----- Token verification (called by access server via tunnel) -----

    @app.post("/_internal/verify-token")
    async def verify_token(request: Request) -> Response:
        """Verify an access token. Called by the access server through the tunnel."""
        from hort.access.tokens import TokenStore

        try:
            data = await request.json()
        except Exception:
            return Response(
                content='{"valid":false}',
                media_type="application/json",
                status_code=400,
            )
        token = data.get("token", "")
        store = TokenStore()
        valid = store.verify(token)
        return Response(
            content=json.dumps({"valid": valid}),
            media_type="application/json",
        )

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
        const _b = document.querySelector('base');
        const _bp = _b ? new URL(_b.href).pathname.replace(/\/$/, '') : '';
        const ws = new WebSocket(proto + '://' + location.host + _bp + '/ws/devreload');
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

    Uses --timeout-graceful-shutdown to force-kill after 5 seconds on
    reload (prevents deadlocks from background tasks that don't exit cleanly).
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
        "--timeout-graceful-shutdown", "5",
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
