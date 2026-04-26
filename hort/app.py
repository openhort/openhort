"""FastAPI application: routes, WebSocket streaming, and server startup."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
import logging
import os
import re
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
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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
    ext_dir = Path(__file__).parent.parent / "llmings" / "core"
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

    # Sandboxed (opaque-origin) iframes treat same-origin asset fetches as
    # cross-origin, so fonts loaded via @font-face require CORS headers.
    # Mark all static + ext responses as CORS-allowed for any origin.
    @app.middleware("http")
    async def _allow_cors_for_static(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") or path.startswith("/ext/") or path.startswith("/sample-data/"):
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Bundled card-host: inline Vue + card-shim + per-llming cards.js +
    # CSS into a single HTML document so each sandboxed iframe needs ONE
    # HTTP request instead of 7+. With Chrome cache partitioning per
    # opaque-origin iframe and HTTP/1.1's 6-conn limit, the unbundled
    # version serialises 19 iframes × 7 requests into multi-second queues.
    _bundle_per_llming: dict[str, tuple[float, bytes]] = {}

    def _build_bundle_for(llming: str) -> bytes:
        host = STATIC_DIR / "card-host.html"
        vue_js = STATIC_DIR / "vendor" / "vue.global.prod.js"
        shim_js = STATIC_DIR / "vendor" / "card-shim.js"
        hort_css = STATIC_DIR / "hort.css"
        ph_reg = STATIC_DIR / "vendor" / "phosphor" / "regular.css"
        ph_fill = STATIC_DIR / "vendor" / "phosphor" / "fill.css"
        files = [host, vue_js, shim_js, hort_css, ph_reg, ph_fill]
        vp = _vue_routes.get(llming.replace("-", "_"))
        if vp is not None:
            files.append(vp)
        max_mt = max(f.stat().st_mtime for f in files)
        cached = _bundle_per_llming.get(llming)
        if cached and cached[0] == max_mt:
            return cached[1]

        # Compile cards.js (cached) for this llming.
        card_js_inline = ""
        if vp is not None:
            try:
                from hort.ext.vue_loader import compile_vue as _cv
                card_js_inline = _vue_cache.get(llming.replace("-", "_"), (0, None))[1] or _cv(vp, llming.replace("-", "_"))
            except Exception:
                card_js_inline = ""

        # Rewrite Phosphor font URLs to absolute paths so the inlined CSS
        # works regardless of the iframe's URL.
        def _rewrite_font_urls(css: str) -> str:
            return css.replace('url("./Phosphor', 'url("/static/vendor/phosphor/Phosphor').replace("url('./Phosphor", "url('/static/vendor/phosphor/Phosphor")

        html = host.read_text()
        # Inline external scripts.
        html = html.replace(
            '<script src="vendor/vue.global.prod.js"></script>',
            "<script>" + vue_js.read_text() + "</script>",
        )
        html = html.replace(
            '<script src="vendor/card-shim.js"></script>',
            "<script>" + shim_js.read_text() + "</script>",
        )
        # Replace external stylesheets with inline <style>.
        for tag, path in [
            ('<link rel="stylesheet" href="vendor/phosphor/regular.css">', ph_reg),
            ('<link rel="stylesheet" href="vendor/phosphor/fill.css">', ph_fill),
            ('<link rel="stylesheet" href="hort.css">', hort_css),
        ]:
            html = html.replace(tag, "<style>" + _rewrite_font_urls(path.read_text()) + "</style>")
        # Inline cards.js — runs AFTER the shim so LlmingClient.register works.
        if card_js_inline:
            html = html.replace("</body>", "<script>/* inline cards.js */\n" + card_js_inline + "\n</script>\n</body>")
        out = html.encode()
        _bundle_per_llming[llming] = (max_mt, out)
        return out

    @app.get("/_card_host")
    async def _card_host_bundle_handler(llming: str = "") -> Response:
        if not llming:
            llming = "weather"  # any default for the warm-pool's empty request
        return Response(content=_build_bundle_for(llming), media_type="text/html")

    # Serve compiled .vue files as JS ({name}.vue → /ext/{name}/static/cards.js)
    _llmings_root = Path(__file__).parent.parent / "llmings"
    _vue_routes: dict[str, Path] = {}  # {dir_name: vue_path}

    for _provider_dir in sorted(_llmings_root.iterdir()) if _llmings_root.is_dir() else []:
        if not _provider_dir.is_dir() or _provider_dir.name.startswith((".", "_")):
            continue
        for ext_path in _provider_dir.iterdir():
            if not ext_path.is_dir():
                continue
            # Check manifest for custom card file name
            _card_name = None
            _manifest_path = ext_path / "manifest.json"
            if _manifest_path.exists():
                try:
                    import json as _json
                    _mdata = _json.loads(_manifest_path.read_text())
                    _card_name = _mdata.get("card")
                except Exception:
                    pass
            # Default: {dir_name}.vue
            if _card_name:
                vue_file = ext_path / _card_name
            else:
                vue_file = ext_path / f"{ext_path.name}.vue"
            if vue_file.exists():
                _vue_routes[ext_path.name] = vue_file

    if _vue_routes:
        from hort.ext.vue_loader import compile_vue

        # Register a dedicated route per vue llming (not a catch-all)
        # Mtime-keyed in-memory cache so 19 sandboxed iframes hitting the
        # same cards.js endpoint don't recompile the .vue source 19 times.
        # In dev, mtime change naturally invalidates on file edit.
        _vue_cache: dict[str, tuple[float, str]] = {}

        def _cached_compile(vp: Path, vn: str) -> str:
            mt = vp.stat().st_mtime
            cached = _vue_cache.get(vn)
            if cached and cached[0] == mt:
                return cached[1]
            js = compile_vue(vp, vn)
            _vue_cache[vn] = (mt, js)
            return js

        for _vue_name, _vue_path in _vue_routes.items():
            def _make_handler(vp: Path, vn: str) -> Any:
                async def handler() -> Response:
                    js = _cached_compile(vp, vn)
                    return Response(content=js, media_type="application/javascript")
                return handler
            app.get(f"/ext/{_vue_name}/static/cards.js")(_make_handler(_vue_path, _vue_name))

    # Serve compiled app.vue files as JS (/ext/{name}/static/app.js)
    _app_routes: dict[str, Path] = {}
    for _provider_dir in sorted(_llmings_root.iterdir()) if _llmings_root.is_dir() else []:
        if not _provider_dir.is_dir() or _provider_dir.name.startswith((".", "_")):
            continue
        for ext_path in _provider_dir.iterdir():
            if not ext_path.is_dir():
                continue
            # Check app.vue, then app/index.vue
            app_vue = ext_path / "app.vue"
            if not app_vue.exists():
                app_vue = ext_path / "app" / "index.vue"
            if app_vue.exists():
                _app_routes[ext_path.name] = app_vue

    if _app_routes:
        from hort.ext.vue_loader import compile_vue as _compile_app

        _app_cache: dict[str, tuple[float, str]] = {}

        def _cached_compile_app(vp: Path, vn: str) -> str:
            mt = vp.stat().st_mtime
            cached = _app_cache.get(vn)
            if cached and cached[0] == mt:
                return cached[1]
            js = _compile_app(vp, vn, mode="app")
            _app_cache[vn] = (mt, js)
            return js

        for _app_name, _app_path in _app_routes.items():
            def _make_app_handler(vp: Path, vn: str) -> Any:
                async def handler() -> Response:
                    js = _cached_compile_app(vp, vn)
                    return Response(content=js, media_type="application/javascript")
                return handler
            app.get(f"/ext/{_app_name}/static/app.js")(_make_app_handler(_app_path, _app_name))

    # Serve demo.js files (/ext/{name}/demo.js)
    for _provider_dir in sorted(_llmings_root.iterdir()) if _llmings_root.is_dir() else []:
        if not _provider_dir.is_dir() or _provider_dir.name.startswith((".", "_")):
            continue
        for ext_path in _provider_dir.iterdir():
            if not ext_path.is_dir():
                continue
            demo_file = ext_path / "demo.js"
            if demo_file.exists():
                def _make_demo_handler(dp: Path) -> Any:
                    async def handler() -> Response:
                        return Response(content=dp.read_text(), media_type="application/javascript",
                                        headers={"Cache-Control": "no-cache"})
                    return handler
                app.get(f"/ext/{ext_path.name}/demo.js")(_make_demo_handler(demo_file))

    # Serve shared demo data directory
    _demo_data_dir = Path(__file__).parent.parent / "sample-data"
    if _demo_data_dir.is_dir():
        app.mount("/sample-data", StaticFiles(directory=str(_demo_data_dir)), name="sample-data")

    # Mount extension static directories (all provider dirs under llmings/)
    for _provider_dir in sorted(_llmings_root.iterdir()) if _llmings_root.is_dir() else []:
        if not _provider_dir.is_dir() or _provider_dir.name.startswith((".", "_")):
            continue
        for ext_path in _provider_dir.iterdir():
            if not ext_path.is_dir():
                continue
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

    # Auth middleware — protects all /api/ endpoints except public allowlist
    from hort.auth import AuthMiddleware
    app.add_middleware(AuthMiddleware)

    _register_targets()
    _register_media_providers()
    _register_routes(app)

    # Llmings — discovery and route registration only (no loading yet).
    # Actual loading + scheduling + connectors happen in the startup event.
    from hort.plugins import load_llmings_sync, setup_llmings, start_llmings, stop_llmings

    llming_registry = setup_llmings(app)

    # Make registry available to WS command handlers
    from hort.commands._registry import set_llming_registry
    set_llming_registry(llming_registry)

    # Mount llming-com debug API and command router for session inspection
    from hort.session import HortRegistry, HortSessionManager
    from llming_com import build_debug_router, build_command_router

    _session_manager = HortSessionManager.get()

    def _session_detail(sid: str, entry: Any) -> dict[str, Any]:
        """Custom detail hook for debug API."""
        from llming_com import SessionContext
        ctx = _session_manager.get_context(sid)
        detail: dict[str, Any] = {
            "active_window_id": entry.active_window_id,
            "active_target_id": entry.active_target_id,
            "stream_active": entry.stream_ws is not None,
            "observer_id": entry.observer_id,
        }
        if ctx:
            detail["connection_type"] = ctx.connection_type.value
            detail["remote_ip"] = ctx.remote_ip
            detail["user_email"] = ctx.user_email
            detail["target_id"] = ctx.target_id
        return detail

    debug_router = build_debug_router(
        HortRegistry.get(),
        prefix="/debug",
        session_detail_hook=_session_detail,
    )
    app.include_router(debug_router, prefix="/api/llming")

    command_router = build_command_router(
        HortRegistry.get(),
        prefix="/debug",
    )
    app.include_router(command_router, prefix="/api/llming")

    # Mount credential management API
    from hort.credentials.api import build_credential_router
    credential_router = build_credential_router()
    app.include_router(credential_router, prefix="/api")

    @app.on_event("startup")
    async def _on_startup() -> None:
        load_llmings_sync(llming_registry)
        await start_llmings(llming_registry)
        logger.info("App startup complete (pid=%d)", os.getpid())

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        logger.info("App shutdown initiated (pid=%d)", os.getpid())
        await stop_llmings(llming_registry)

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
        if not hasattr(app.state, "cloud_tokens"):
            app.state.cloud_tokens = {}
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


def _temp_token_path() -> Path:
    from hort.hort_config import hort_data_dir
    return hort_data_dir() / "current-temp-token"

_TEMP_TOKEN_FILE = _temp_token_path()


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
                    from llmings.core.linux_windows.linux_windows import (  # noqa: platform provider (in-process for latency)
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


async def _notify_llmings_viewer(event: str, session_id: str, controller: Any = None) -> None:
    """Notify all llmings about viewer connect/disconnect."""
    from hort.llming.base import Llming

    if not hasattr(app.state, "llming_registry"):
        return
    for name, inst in app.state.llming_registry._instances.items():
        if not isinstance(inst, Llming):
            continue
        try:
            if event == "connect":
                await inst.on_viewer_connect(session_id, controller)
            elif event == "disconnect":
                await inst.on_viewer_disconnect(session_id)
        except Exception:
            logger.exception("Llming %s failed on viewer %s", name, event)


def _register_media_providers() -> None:
    """Register unified media providers with the SourceRegistry.

    Only ScreenProvider is registered here. CameraProvider is owned
    by the llming-cam extension which registers it on activate().
    """
    from hort.media import SourceRegistry
    from hort.media_screen import ScreenProvider

    registry = SourceRegistry.get()
    registry.register("screen", ScreenProvider())


def _register_targets() -> None:
    """Register platform targets available on this machine."""
    from hort.targets import TargetInfo, TargetRegistry

    registry = TargetRegistry.get()

    # Register local macOS target (only on macOS)
    if sys.platform == "darwin":
        try:
            from llmings.core.macos_windows.macos_windows import (  # noqa: platform provider (in-process)
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
            from llmings.core.linux_native.linux_native import (  # noqa: platform provider (in-process)
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
            from llmings.core.windows_native.windows_native import (  # noqa: platform provider (in-process)
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
        path = Path(__file__).parent.parent / "llmings" / "core" / "peer2peer" / "static" / "viewer.html"
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
    async def get_hash() -> dict[str, Any]:
        from hort.session import HortRegistry
        registry = HortRegistry.get()
        return {
            "hash": _static_hash(),
            "dev": str(app.state.dev_mode),
            "observers": registry.observer_count(),
        }

    @app.post("/api/debug/demo/{action}")
    async def debug_demo(action: str = "on") -> dict[str, Any]:
        """Control demo mode on all connected viewers.

        Actions: 'on', 'off', 'toggle'
        Pushes a demo command via WS to all sessions.
        """
        if action not in ("on", "off", "toggle"):
            return {"error": f"Invalid action: {action}. Use on/off/toggle."}
        from hort.session import HortRegistry
        registry = HortRegistry.get()
        count = 0
        for sid in list(registry._sessions.keys()):
            try:
                entry = registry.get_session(sid)
                if entry and hasattr(entry, "controller") and entry.controller:
                    await entry.controller.send({"type": "demo.set", "action": action})
                    count += 1
            except Exception:
                pass
        return {"ok": True, "action": action, "viewers_notified": count}

    @app.get("/api/debug/tools")
    async def debug_tools() -> list[dict[str, Any]]:
        """List all MCP tools from all llmings with full schemas.

        Used by the proxy MCP bridge to discover tools without loading extensions.
        """
        from hort.llming.base import Llming

        if not hasattr(app.state, "llming_registry"):
            return []
        tools: list[dict[str, Any]] = []
        for name, inst in app.state.llming_registry._instances.items():
            if not isinstance(inst, Llming):
                continue
            for t in inst.get_mcp_tools():
                tools.append({
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                    "_llming": name,
                    "_power": t.name,
                })
        return tools

    @app.get("/api/debug/souls")
    async def debug_souls() -> list[dict[str, Any]]:
        """Get all llming SOUL texts for system prompt building."""
        from hort.llming.base import Llming

        if not hasattr(app.state, "llming_registry"):
            return []
        souls: list[dict[str, Any]] = []
        for name, inst in app.state.llming_registry._instances.items():
            if not isinstance(inst, Llming):
                continue
            soul = inst.soul
            if soul:
                souls.append({"llming": name, "soul": soul})
        return souls

    @app.post("/api/debug/eval")
    async def debug_eval(request: Request) -> dict[str, Any]:
        """Execute JS in the active browser session and return the result."""
        from hort.session import HortRegistry, HortSessionEntry
        body = await request.json()
        code = body.get("code", "")
        if not code:
            return {"error": "no code"}

        registry = HortRegistry.get()
        for sid, entry in registry._sessions.items():
            if entry.stream_ws is not None or getattr(entry, "controller", None):
                ctrl = getattr(entry, "controller", None)
                if ctrl and hasattr(ctrl, "eval_js"):
                    result = await ctrl.eval_js(code)
                    return {"session_id": sid, **result}
        return {"error": "no active browser session"}

    @app.get("/api/debug/console")
    async def debug_console(level: str = "", pattern: str = "") -> dict[str, Any]:
        """Read browser console logs from the active session."""
        from hort.session import HortRegistry
        registry = HortRegistry.get()
        for sid, entry in registry._sessions.items():
            ctrl = getattr(entry, "controller", None)
            if ctrl and hasattr(ctrl, "get_console_logs"):
                result = await ctrl.get_console_logs(level=level, pattern=pattern)
                return {"session_id": sid, **result}
        return {"error": "no active browser session"}

    @app.post("/api/debug/call")
    async def debug_call_llming(request: Request) -> dict[str, Any]:
        """Route a power call to a specific llming. Returns the result."""
        from hort.llming.base import Llming
        body = await request.json()
        llming_name = body.get("llming", "")
        power = body.get("power", "")
        args = body.get("args", {})

        if not hasattr(app.state, "llming_registry"):
            return {"error": "no registry"}
        inst = app.state.llming_registry.get_instance(llming_name)
        if inst is None:
            return {"error": f"llming '{llming_name}' not found"}
        if not isinstance(inst, Llming):
            return {"error": f"'{llming_name}' is not a Llming"}

        result = await inst.execute_power(power, args)
        if isinstance(result, str):
            return {"result": result}
        if isinstance(result, dict):
            return {"result": result}
        return {"result": str(result)}

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
        if hasattr(app.state, "llming_registry"):  # pragma: no cover
            from hort.ext.connectors import ConnectorBase

            for name, inst in app.state.llming_registry._instances.items():
                if isinstance(inst, ConnectorBase):
                    status = inst.vault.get("state") if hasattr(inst, "vault") else {}
                    messaging[inst.connector_id] = {
                        "active": status.get("active", False),
                        "llming_id": name,
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
        """Get system config by ID (connectors, etc). NOT for llming data — use /api/llmings/{id}/store."""
        from hort.config import get_store

        config = get_store().get(plugin_id)
        return Response(content=json.dumps(config), media_type="application/json")

    @app.post("/api/config/{plugin_id:path}")
    async def update_config(plugin_id: str, request: Request) -> Response:
        """Update config for a llming by its unique ID (merge)."""
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

        Detects connection type (LAN, proxy, P2P) and stores it in
        the session context via ``HortSessionManager``.
        """
        from llming_com import ConnectionType, SessionContext
        from hort.session import HortSessionEntry, HortSessionManager

        manager = HortSessionManager.get()

        # Detect connection type
        forwarded_via = request.headers.get("x-forwarded-via", "")
        if forwarded_via == "p2p":
            conn_type = ConnectionType.P2P
        elif forwarded_via == "proxy":
            conn_type = ConnectionType.PROXY
        else:
            conn_type = ConnectionType.LAN

        is_local = conn_type == ConnectionType.LAN

        entry = HortSessionEntry(user_id="viewer")
        context = SessionContext(
            connection_type=conn_type,
            remote_ip=request.client.host if request.client else "",
        )
        session_id, auth_token = manager.create_session(entry, context=context)
        return {"session_id": session_id, "auth_token": auth_token, "is_local": is_local}

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
        if getattr(app.state, "llming_registry", None):
            plugin = app.state.llming_registry.get_instance("peer2peer")
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
        if not hasattr(app.state, "llming_registry"):
            return {"error": "plugins not loaded"}
        plugin = app.state.llming_registry.get_instance("peer2peer")
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
        if not hasattr(app.state, "llming_registry"):
            return {"error": "plugins not loaded"}
        plugin = app.state.llming_registry.get_instance("peer2peer")
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
        if not hasattr(app.state, "llming_registry"):
            return {"devices": []}
        plugin = app.state.llming_registry.get_instance("peer2peer")
        if not plugin or not hasattr(plugin, "_device_store") or not plugin._device_store:
            return {"devices": []}
        return {"devices": plugin._device_store.list_devices()}

    @app.delete("/api/p2p/devices")
    async def p2p_device_revoke(request: Request) -> dict[str, Any]:
        """Revoke a paired device by token_hash."""
        if not hasattr(app.state, "llming_registry"):
            return {"error": "plugins not loaded"}
        plugin = app.state.llming_registry.get_instance("peer2peer")
        if not plugin or not hasattr(plugin, "_device_store") or not plugin._device_store:
            return {"error": "Device store not available"}
        body = await request.json()
        token_hash = body.get("token_hash", "")
        if not token_hash:
            return {"error": "token_hash required"}
        ok = plugin._device_store.revoke(token_hash)
        return {"ok": ok}

    # ===== Hosted Apps API + reverse proxy =====

    @app.get("/api/hosted-apps/catalog")
    async def hosted_apps_catalog() -> dict[str, Any]:
        """List available app types."""
        from llmings.core.hosted_apps.catalog import get_catalog  # noqa: static data (TODO: route via IPC)
        return {"catalog": get_catalog()}

    @app.post("/api/hosted-apps/instances")
    async def hosted_apps_create(request: Request) -> dict[str, Any]:
        """Create a new hosted app instance."""
        plugin = app.state.llming_registry.get_instance("hosted-apps") if hasattr(app.state, "llming_registry") else None
        if not plugin:
            return {"error": "Hosted apps not available"}
        body = await request.json()
        app_type = body.get("app_type", "")
        name = body.get("name", app_type)
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, plugin.create_instance, app_type, name)
            return result
        except Exception as exc:
            return {"error": str(exc)}

    @app.get("/api/hosted-apps/instances")
    async def hosted_apps_list() -> dict[str, Any]:
        """List all instances."""
        plugin = app.state.llming_registry.get_instance("hosted-apps") if hasattr(app.state, "llming_registry") else None
        if not plugin:
            return {"instances": []}
        return {"instances": plugin.list_instances()}

    @app.post("/api/hosted-apps/instances/{name}/start")
    async def hosted_apps_start(name: str) -> dict[str, Any]:
        plugin = app.state.llming_registry.get_instance("hosted-apps") if hasattr(app.state, "llming_registry") else None
        if not plugin:
            return {"error": "not available"}
        ok = await asyncio.get_event_loop().run_in_executor(None, plugin.start_instance, name)
        return {"ok": ok}

    @app.post("/api/hosted-apps/instances/{name}/stop")
    async def hosted_apps_stop(name: str) -> dict[str, Any]:
        plugin = app.state.llming_registry.get_instance("hosted-apps") if hasattr(app.state, "llming_registry") else None
        if not plugin:
            return {"error": "not available"}
        ok = await asyncio.get_event_loop().run_in_executor(None, plugin.stop_instance, name)
        return {"ok": ok}

    @app.delete("/api/hosted-apps/instances/{name}")
    async def hosted_apps_destroy(name: str) -> dict[str, Any]:
        plugin = app.state.llming_registry.get_instance("hosted-apps") if hasattr(app.state, "llming_registry") else None
        if not plugin:
            return {"error": "not available"}
        ok = await asyncio.get_event_loop().run_in_executor(None, plugin.destroy_instance, name)
        return {"ok": ok}

    @app.get("/app/{instance}/")
    @app.get("/app/{instance}")
    async def hosted_app_redirect(instance: str, request: Request) -> Response:
        """Redirect to the proxy path where relative URLs resolve correctly."""
        location = "./~/" if request.url.path.endswith("/") else f"{instance}/~/"
        return Response(status_code=302, headers={"Location": location})

    def _hosted_app_bootstrap() -> bytes:
        """Rewrite rooted browser URLs relative to the visible /~/ page prefix."""
        js = r"""
<script>
(function() {
  function getPrefix() {
    var p = window.location.pathname || '';
    if (p.endsWith('/~')) return p;
    var i = p.indexOf('/~/');
    return i >= 0 ? p.slice(0, i + 2) : '';
  }
  var PREFIX = getPrefix();
  function rewriteUrl(input) {
    try {
      var url = input instanceof URL ? input : new URL(String(input), window.location.href);
      if (url.origin !== window.location.origin) return input;
      if (!PREFIX) return input;
      if (!url.pathname.startsWith('/')) return input;
      if (url.pathname.startsWith(PREFIX + '/')
          || url.pathname === PREFIX
          || url.pathname.startsWith('/api/')
          || url.pathname.startsWith('/ws/')
          || url.pathname.startsWith('/ext/')
          || url.pathname.startsWith('/app/')
          || url.pathname.startsWith('/proxy/')
          || url.pathname.startsWith('/guide/')
          || url.pathname.startsWith('/hortmap')
          || url.pathname.startsWith('/viewer')
          || url.pathname.startsWith('/static/vendor/')
          || url.pathname === '/') {
        return input;
      }
      return PREFIX + url.pathname + url.search + url.hash;
    } catch (_) {
      return input;
    }
  }
  function rewriteInit(init) {
    if (!init || !init.headers || init.headers instanceof Headers) return init;
    return init;
  }
  var _fetch = window.fetch.bind(window);
  window.fetch = function(input, init) {
    if (typeof input === 'string' || input instanceof URL) {
      return _fetch(rewriteUrl(input), rewriteInit(init));
    }
    if (input instanceof Request) {
      var nextUrl = rewriteUrl(input.url);
      if (nextUrl === input.url) return _fetch(input, init);
      return _fetch(new Request(nextUrl, input), init);
    }
    return _fetch(input, init);
  };
  var _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url) {
    return _open.call(this, method, rewriteUrl(url), arguments[2], arguments[3], arguments[4]);
  };
  var NativeWS = window.WebSocket;
  window.WebSocket = function(url, protocols) {
    return protocols === undefined ? new NativeWS(rewriteUrl(url)) : new NativeWS(rewriteUrl(url), protocols);
  };
  window.WebSocket.prototype = NativeWS.prototype;
  window.WebSocket.CONNECTING = NativeWS.CONNECTING;
  window.WebSocket.OPEN = NativeWS.OPEN;
  window.WebSocket.CLOSING = NativeWS.CLOSING;
  window.WebSocket.CLOSED = NativeWS.CLOSED;
  if (window.EventSource) {
    var NativeES = window.EventSource;
    window.EventSource = function(url, config) {
      return new NativeES(rewriteUrl(url), config);
    };
    window.EventSource.prototype = NativeES.prototype;
  }
  var _push = history.pushState.bind(history);
  history.pushState = function(state, title, url) {
    return _push(state, title, typeof url === 'string' ? rewriteUrl(url) : url);
  };
  var _replace = history.replaceState.bind(history);
  history.replaceState = function(state, title, url) {
    return _replace(state, title, typeof url === 'string' ? rewriteUrl(url) : url);
  };
})();
</script>
"""
        return js.encode("utf-8")

    def _relative_to_app_root(path: str, rooted_location: str) -> str:
        """Convert a rooted app redirect (/login) to a relative /~/ redirect."""
        target = rooted_location.lstrip("/")
        if not path:
            return f"./{target}"
        depth = path.count("/")
        return ("../" * depth) + target

    def _instance_from_referer(request: Request) -> str | None:
        """Extract hosted app instance name from Referer for root asset fallbacks."""
        referer = request.headers.get("referer", "")
        if not referer:
            cookie_instance = request.cookies.get("ohapp_instance", "").strip()
            return cookie_instance or None
        try:
            path = httpx.URL(referer).path
        except Exception:
            cookie_instance = request.cookies.get("ohapp_instance", "").strip()
            return cookie_instance or None
        m = re.search(r"/app/([^/]+)/~(?:/|$)", path)
        if m:
            return m.group(1)
        cookie_instance = request.cookies.get("ohapp_instance", "").strip()
        return cookie_instance or None

    def _rewrite_hosted_app_json(body: bytes, container_url: str, instance: str) -> bytes:
        """Rewrite absolute upstream self-URLs inside JSON payloads to hosted-app paths."""
        try:
            import httpx as httpx_client
            upstream = httpx_client.URL(container_url)
        except Exception:
            return body
        app_base = f"/app/{instance}/~"
        candidates = {
            container_url.rstrip("/"),
            f"{upstream.scheme}://{upstream.host}",
            f"{upstream.scheme}://{upstream.host}{':' + str(upstream.port) if upstream.port else ''}",
            "http://localhost:5678",
            "https://localhost:5678",
            "http://127.0.0.1:5678",
            "https://127.0.0.1:5678",
        }
        rewritten = body
        for candidate in sorted({c for c in candidates if c}, key=len, reverse=True):
            rewritten = rewritten.replace(candidate.encode(), app_base.encode())
        return rewritten

    def _normalize_hosted_app_json(body: bytes, path: str) -> bytes:
        """Fill in fields that some hosted app frontends assume always exist."""
        if path != "rest/settings":
            return body
        try:
            payload = json.loads(body)
        except Exception:
            return body
        data = payload.get("data")
        if not isinstance(data, dict):
            return body
        data.setdefault("license", {"planName": "Community", "consumerId": None, "environment": "production"})
        data.setdefault("security", {"blockFileAccessToN8nFiles": False})
        data.setdefault("concurrency", -1)
        data.setdefault("pruning", {"isEnabled": False})
        data.setdefault("versionNotifications", {"enabled": False})
        data.setdefault("banners", {"dismissed": []})
        data.setdefault("versionCli", "")
        enterprise = data.setdefault("enterprise", {})
        if isinstance(enterprise, dict):
            enterprise.setdefault("projects", {"team": {"limit": 0}})
            projects = enterprise.get("projects")
            if isinstance(projects, dict):
                projects.setdefault("team", {"limit": 0})
                team = projects.get("team")
                if isinstance(team, dict):
                    team.setdefault("limit", 0)
        try:
            return json.dumps(payload, separators=(",", ":")).encode()
        except Exception:
            return body

    def _hosted_app_upstream_path(path: str, request: Request) -> str:
        """Map browser-visible SPA routes back to the upstream app shell."""
        method = request.method.upper()
        if method not in {"GET", "HEAD"}:
            return path
        if not path:
            return path
        if path.startswith(("assets/", "static/", "rest/", "favicon.ico")):
            return path
        if "." in path.rsplit("/", 1)[-1]:
            return path
        return ""

    def _browser_app_base(request: Request) -> str:
        """Return the visible hosted-app mount path with trailing slash."""
        path = request.url.path
        if "/~/" in path:
            return path.split("/~/", 1)[0] + "/~/"
        if path.endswith("/~"):
            return path + "/"
        return "/"

    async def _proxy_hosted_app(instance: str, path: str, request: Request) -> Response:
        """Reverse proxy HTTP to a hosted app container."""
        logger.warning("HOSTED APP PROXY hit instance=%s path=%r method=%s", instance, path, request.method)
        if not hasattr(app.state, "llming_registry"):
            return Response(content="Plugins not loaded", status_code=503)
        plugin = app.state.llming_registry.get_instance("hosted-apps")
        if not plugin:
            return Response(content="Hosted apps not available", status_code=503)
        container_url = plugin.get_container_url(instance)
        if not container_url:
            return Response(content="Instance not found or not running", status_code=404)

        import httpx as httpx_client

        async with httpx_client.AsyncClient(timeout=30.0) as client:
            headers = dict(request.headers)
            headers.pop("host", None)
            headers.pop("accept-encoding", None)
            headers.pop("Accept-Encoding", None)
            headers["accept-encoding"] = "identity"
            try:
                # Forward to container — strip the /app/{instance}/~/ prefix
                qs = '?' + str(request.query_params) if request.query_params else ''
                upstream_path = _hosted_app_upstream_path(path, request)
                resp = await client.request(
                    method=request.method,
                    url=f"{container_url}/{upstream_path}{qs}",
                    headers=headers,
                    content=await request.body(),
                )
            except Exception as exc:
                return Response(content=f"Container unreachable: {exc}", status_code=502)

            resp_headers = dict(resp.headers)
            resp_headers["x-hosted-app-proxy"] = "1"
            for h in ["x-frame-options", "X-Frame-Options", "content-security-policy",
                       "Content-Security-Policy", "transfer-encoding", "connection"]:
                resp_headers.pop(h, None)

            body = resp.content
            ct = resp_headers.get("content-type", resp_headers.get("Content-Type", ""))
            is_html = "text/html" in ct
            is_js = ct.startswith("application/javascript") or "text/javascript" in ct or path.endswith(".js")
            is_css = ct.startswith("text/css") or path.endswith(".css")
            is_json = "application/json" in ct or path.endswith(".json")
            content_encoding = resp_headers.get("content-encoding", resp_headers.get("Content-Encoding", ""))

            if content_encoding.lower() == "gzip" and (is_html or is_js or is_css or is_json):
                try:
                    body = gzip.decompress(body)
                    resp_headers.pop("content-encoding", None)
                    resp_headers.pop("Content-Encoding", None)
                    resp_headers.pop("content-length", None)
                    resp_headers.pop("Content-Length", None)
                except OSError:
                    pass

            location = resp_headers.get("location", resp_headers.get("Location"))
            if location and location.startswith("/"):
                resp_headers["location"] = _relative_to_app_root(path, location)
                resp_headers.pop("Location", None)
                resp_headers.pop("content-length", None)
                resp_headers.pop("Content-Length", None)

            if is_html:
                resp_headers["x-hosted-app-html"] = "1"
                resp_headers["set-cookie"] = f"ohapp_instance={instance}; Path=/; SameSite=Lax"
                body = b"<!-- hosted-app-html -->\n" + body
                body = body.replace(b'href="/', b'href="./')
                body = body.replace(b"href='/", b"href='./")
                body = body.replace(b'src="/', b'src="./')
                body = body.replace(b"src='/", b"src='./")
                body = body.replace(b'action="/', b'action="./')
                body = body.replace(b"action='/", b"action='./")
                if b"<head>" in body:
                    body = body.replace(
                        b"<head>",
                        b'<head><base href="./">' + _hosted_app_bootstrap(),
                        1,
                    )
                elif b"<html>" in body:
                    body = body.replace(
                        b"<html>",
                        b"<html><head><base href=\"./\">" + _hosted_app_bootstrap() + b"</head>",
                        1,
                    )
                else:
                    body = _hosted_app_bootstrap() + body
                resp_headers.pop("content-length", None)
                resp_headers.pop("Content-Length", None)

            # Rewrite rooted URLs to page-relative URLs so they work both under
            # /app/... and /proxy/{host}/app/... without container-specific config.
            if is_js:
                if path == "static/base-path.js":
                    body = f'window.BASE_PATH = "{_browser_app_base(request)}";'.encode()
                body = body.replace(b'"/assets/', b'"./assets/')
                body = body.replace(b"'/assets/", b"'./assets/")
                body = body.replace(b'"/static/', b'"./static/')
                body = body.replace(b"'/static/", b"'./static/")
                body = body.replace(b'"/rest/', b'"./rest/')
                body = body.replace(b"'/rest/", b"'./rest/")
                body = body.replace(b'"/favicon', b'"./favicon')
                body = body.replace(b"'/favicon", b"'./favicon")
                body = body.replace(b'"/login', b'"./login')
                body = body.replace(b"'/login", b"'./login")
                body = body.replace(b'"/logout', b'"./logout')
                body = body.replace(b"'/logout", b"'./logout")
                body = body.replace(b"window.BASE_PATH = '/'", f'window.BASE_PATH = "{_browser_app_base(request)}"'.encode())
                body = body.replace(b'window.BASE_PATH = "/"', f'window.BASE_PATH = "{_browser_app_base(request)}"'.encode())
                resp_headers.pop("content-length", None)
                resp_headers.pop("Content-Length", None)

            # Most hosted-app stylesheets live under ./assets/*.css, so ../assets
            # keeps root URLs inside the same visible /~/ prefix.
            if is_css:
                body = body.replace(b'url("/assets/', b'url("../assets/')
                body = body.replace(b"url('/assets/", b"url('../assets/")
                body = body.replace(b'url(/assets/', b'url(../assets/')
                body = body.replace(b'url("/static/', b'url("../static/')
                body = body.replace(b"url('/static/", b"url('../static/")
                body = body.replace(b'url(/static/', b'url(../static/')
                resp_headers.pop("content-length", None)
                resp_headers.pop("Content-Length", None)

            if is_json:
                body = _rewrite_hosted_app_json(body, container_url, instance)
                body = _normalize_hosted_app_json(body, path)
                resp_headers.pop("content-length", None)
                resp_headers.pop("Content-Length", None)

            return Response(
                content=body,
                status_code=resp.status_code,
                headers=resp_headers,
            )

    @app.api_route(
        "/app/{instance}/~/",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    @app.api_route(
        "/app/{instance}/~",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def proxy_hosted_app_root(instance: str, request: Request) -> Response:
        return await _proxy_hosted_app(instance, "", request)

    @app.api_route(
        "/app/{instance}/~/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def proxy_hosted_app(instance: str, path: str, request: Request) -> Response:
        return await _proxy_hosted_app(instance, path, request)

    @app.api_route(
        "/assets/{path:path}",
        methods=["GET", "HEAD", "OPTIONS"],
    )
    async def proxy_hosted_app_root_assets(path: str, request: Request) -> Response:
        """Fallback for runtime-generated absolute asset URLs."""
        instance = _instance_from_referer(request)
        if not instance:
            return Response(content="Not found", status_code=404)
        return await _proxy_hosted_app(instance, f"assets/{path}", request)

    @app.get("/favicon.ico")
    async def proxy_hosted_app_root_favicon(request: Request) -> Response:
        instance = _instance_from_referer(request)
        if not instance:
            return Response(content="Not found", status_code=404)
        return await _proxy_hosted_app(instance, "favicon.ico", request)

    @app.websocket("/app/{instance}/~/{path:path}")
    async def proxy_hosted_app_ws(websocket: WebSocket, instance: str, path: str) -> None:
        """WebSocket proxy to a hosted app container."""
        if not hasattr(app.state, "llming_registry"):
            await websocket.close(code=1013)
            return
        plugin = app.state.llming_registry.get_instance("hosted-apps")
        if not plugin:
            await websocket.close(code=1013)
            return
        container_url = plugin.get_container_url(instance)
        if not container_url:
            await websocket.close(code=1013)
            return

        import websockets as ws_lib  # type: ignore[import-untyped]

        qs = '?' + str(websocket.query_params) if websocket.query_params else ''
        ws_url = container_url.replace("http://", "ws://") + f"/{path}{qs}"

        try:
            subprotocols = websocket.headers.get("sec-websocket-protocol", "")
            origin = websocket.headers.get("origin")
            if origin:
                remote = ws_lib.connect(
                    ws_url,
                    origin=origin,
                    subprotocols=[p.strip() for p in subprotocols.split(",") if p.strip()] or None,
                )
            else:
                remote = ws_lib.connect(
                    ws_url,
                    subprotocols=[p.strip() for p in subprotocols.split(",") if p.strip()] or None,
                )
            async with remote as remote_ws:
                await websocket.accept(subprotocol=remote_ws.subprotocol)
                async def forward_to_remote() -> None:
                    try:
                        while True:
                            data = await websocket.receive()
                            if "text" in data:
                                await remote_ws.send(data["text"])
                            elif "bytes" in data and data["bytes"]:
                                await remote_ws.send(data["bytes"])
                    except Exception:
                        pass

                async def forward_to_client() -> None:
                    try:
                        async for msg in remote_ws:
                            if isinstance(msg, str):
                                await websocket.send_text(msg)
                            else:
                                await websocket.send_bytes(msg)
                    except Exception:
                        pass

                await asyncio.gather(forward_to_remote(), forward_to_client())
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

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
            # Mount WS command router (llmings.list, config.get, etc.)
            from hort.commands import build_ws_router
            controller.mount_router(build_ws_router())
            entry.controller = controller
            await controller.send({"type": "connected", "version": "0.1.0"})
            # Notify all llmings that a viewer connected
            await _notify_llmings_viewer("connect", session_id, controller)

        async def on_message(entry: object, msg: dict[str, Any]) -> None:
            assert isinstance(entry, HortSessionEntry)
            if entry.controller:
                await entry.controller.handle_message(msg)

        async def on_disconnect(sid: str, entry: object) -> None:
            assert isinstance(entry, HortSessionEntry)
            # Clean up card API subscriptions
            from hort.commands.card_api import remove_viewer
            remove_viewer(sid)
            # Notify all llmings that a viewer disconnected
            await _notify_llmings_viewer("disconnect", sid)
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
            rate_limit=2000,  # stream_ack at 15fps = 900/min + UI messages
        )

    @app.websocket("/ws/stream/{session_id}")
    async def session_stream(websocket: WebSocket, session_id: str) -> None:
        """Binary stream channel — JPEG frames for a window."""
        from hort.session import HortRegistry
        from hort.stream import run_stream

        registry: HortRegistry = HortRegistry.get()  # type: ignore[assignment]
        await run_stream(websocket, session_id, registry)

    @app.websocket("/ws/camera/{session_id}/{source_id:path}")
    async def camera_upload_ws(websocket: WebSocket, session_id: str, source_id: str = "") -> None:
        """Binary WebSocket for browser camera frames (client → server).

        The browser sends WebP frames, server buffers the latest one.
        ACK-based flow control: server sends ``camera_ack`` after each frame.
        Max 1 frame in flight — no pile-up on slow connections.
        """
        from hort.media import SourceRegistry
        from hort.session import HortRegistry

        registry = HortRegistry.get()
        entry = registry.get_session(session_id)
        if not entry:
            await websocket.close(code=4004, reason="Session not found")
            return

        await websocket.accept()

        # Find the browser camera session — by source_id param or legacy controller attr
        if not source_id:
            controller = getattr(entry, "controller", None)
            source_id = getattr(controller, "_browser_camera_source_id", "") if controller else ""
        if not source_id:
            await websocket.close(code=4005, reason="No camera offered — send camera_offer first")
            return

        cam_provider = SourceRegistry.get().get_provider("camera")
        if not cam_provider:
            await websocket.close(code=4006, reason="No camera provider")
            return

        session = cam_provider._sessions.get(source_id)
        if not session:
            await websocket.close(code=4007, reason="Camera session not found")
            return

        logger.info("Browser camera WS connected: %s", source_id)
        try:
            while True:
                data = await websocket.receive_bytes()
                if len(data) < 10:
                    continue
                session.receive_frame(data)
                await websocket.send_text('{"type":"camera_ack"}')
        except Exception:
            pass
        finally:
            # Clean up: stop the session so it's not shown as active
            if cam_provider and source_id:
                stale = cam_provider._sessions.get(source_id)
                if stale:
                    stale.stop()
                    cam_provider._sessions.pop(source_id, None)
            logger.info("Browser camera WS disconnected and cleaned up: %s", source_id)

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

    # SPA fallback — serve index.html for 404s that look like llming routes.
    # This avoids catch-all path params that shadow other routes.
    _spa_providers: set[str] = set()
    _ext_root = Path(__file__).parent.parent / "llmings"
    if _ext_root.exists():
        for p in _ext_root.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                _spa_providers.add(p.name)  # e.g. "core"

    @app.exception_handler(404)
    async def _spa_404_handler(request: Request, exc: HTTPException) -> Response:
        """Serve SPA for paths like /llming/core/llming-lens/screens/-1."""
        path = request.url.path.lstrip("/")
        parts = path.split("/")
        # Match /llming/{provider}/{name}[/{sub}...]
        if len(parts) >= 3 and parts[0] == "llming" and parts[1] in _spa_providers:
            return await viewer_page()
        return Response(
            content=json.dumps({"detail": "Not Found"}),
            status_code=404,
            media_type="application/json",
        )


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
    let wasConnected = false;
    let reconnectAttempts = 0;
    function connect() {
        const _b = document.querySelector('base');
        const _bp = _b ? new URL(_b.href).pathname.replace(/\/$/, '') : '';
        const url = proto + '://' + location.host + _bp + '/ws/devreload';
        const ws = new WebSocket(url);
        ws.onopen = function() {
            if (wasConnected) {
                console.log('[dev] server back after ' + reconnectAttempts + ' retries — reloading page');
                location.reload();
                return;
            }
            wasConnected = true;
            reconnectAttempts = 0;
            console.log('[dev] hot-reload connected');
        };
        ws.onmessage = function(e) {
            const msg = JSON.parse(e.data);
            if (msg.type === 'reload') {
                console.log('[dev] static files changed — reloading');
                location.reload();
            }
        };
        ws.onclose = function() {
            reconnectAttempts++;
            if (reconnectAttempts === 1) console.log('[dev] server disconnected, waiting for restart...');
            setTimeout(connect, 2000);
        };
        ws.onerror = function() {}; // suppress console noise
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
