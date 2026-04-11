"""Llming lifecycle — discovery, loading, scheduling, and API routes.

Extracted from app.py to keep files focused. Called by ``create_app()``
to wire llmings into the FastAPI application.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response

from hort.ext.registry import ExtensionRegistry

logger = logging.getLogger("hort.llmings")

EXTENSIONS_DIR = Path(__file__).parent.parent / "llmings"


def setup_llmings(app: FastAPI) -> ExtensionRegistry:
    """Discover llmings and register API routes. Returns the registry.

    Call this during ``create_app()``. The actual loading happens
    in the startup event (needs a running event loop for schedulers).
    """
    registry = ExtensionRegistry()
    registry.set_app(app)
    if EXTENSIONS_DIR.exists():
        registry.discover(EXTENSIONS_DIR)
    app.state.llming_registry = registry
    # Backward-compatible alias
    app.state.plugin_registry = registry
    _register_llming_routes(app, registry)
    return registry


# Backward-compatible alias
setup_plugins = setup_llmings


def load_llmings_sync(registry: ExtensionRegistry) -> None:  # pragma: no cover
    """Load llmings — grouped manifests go to subprocesses, ungrouped load in-process."""
    from hort.config import get_store
    store = get_store()

    # Separate grouped (subprocess) from ungrouped (in-process)
    grouped: dict[str, list] = {}  # {group_name: [manifest, ...]}
    ungrouped: list = []

    for manifest in registry._manifests:
        if not registry.is_compatible(manifest):
            continue
        if manifest.group:
            grouped.setdefault(manifest.group, []).append(manifest)
        else:
            ungrouped.append(manifest)

    # Load ungrouped llmings in-process (existing behavior)
    for manifest in ungrouped:
        cfg = store.get(manifest.name)
        registry.load_extension(manifest, cfg)

    # Store grouped manifests for async subprocess spawning in start_llmings
    registry._grouped_manifests = grouped  # type: ignore[attr-defined]

    loaded = list(registry._instances.keys())
    group_names = list(grouped.keys())
    group_count = sum(len(v) for v in grouped.values())
    logger.info("Loaded %d llmings in-process, %d in %d groups (subprocess)", len(loaded), group_count, len(group_names))


# Backward-compatible alias
load_plugins_sync = load_llmings_sync


async def start_llmings(registry: ExtensionRegistry) -> None:  # pragma: no cover
    """Start all llmings — subprocesses, schedulers, @on subscriptions.

    Grouped llmings are spawned as subprocesses. Ungrouped ones
    (already loaded in-process) get their schedulers and subscriptions wired.
    """
    import asyncio

    from hort.config import get_store
    from hort.ext.scheduler import JobSpec
    from hort.llming.base import Llming
    from hort.llming.decorators import collect_subscriptions, collect_ready_handlers
    from hort.llming.pulse import PulseBus

    bus = PulseBus.get()
    ready_set: set[str] = set()
    ready_waiters: list[tuple[tuple[str, ...], Any]] = []
    store = get_store()

    # ── Spawn subprocess groups ──
    grouped = getattr(registry, "_grouped_manifests", {})
    if grouped:
        from hort.lifecycle.llming_process import GroupProcess

        async def _spawn_group(gname: str, manifests: list) -> None:
            manifest_paths = {m.name: str(m.path) + "/manifest.json" for m in manifests}
            proc = GroupProcess(gname, manifest_paths)
            try:
                started = await proc.start()
                if not started:
                    logger.error("Failed to start group %s", gname)
                    return

                ready = await proc.wait_ready(timeout=10)
                if not ready:
                    logger.warning("Group %s not ready in time", gname)

                for m in manifests:
                    cfg = store.get(m.name) or {}
                    await proc.activate_llming(m.name, cfg)

                for name, proxy in proc.proxies.items():
                    registry._instances[name] = proxy
                    from hort.llming.bus import MessageBus
                    MessageBus.get().register(name, proxy)
                    ready_set.add(name)

                logger.info("Group %s: %s", gname, list(manifest_paths.keys()))
            except Exception:
                logger.exception("Failed to start group %s", gname)

        # Spawn all groups as background tasks (don't block startup)
        for gname, manifests in grouped.items():
            asyncio.create_task(_spawn_group(gname, manifests))

    # ── Wire in-process + subprocess llmings ──

    for name, inst in registry._instances.items():
        if not isinstance(inst, Llming):
            continue

        # Build @power handler map
        inst._build_power_map()

        # Wire @on subscriptions
        for channel, handler in collect_subscriptions(inst):
            bus.subscribe_channel(channel, handler)

        # Collect @on_ready handlers
        for deps, handler in collect_ready_handlers(inst):
            ready_waiters.append((deps, handler))

        # Start manifest-declared scheduler jobs
        manifest = registry.get_manifest(name)
        if manifest:
            for jm in manifest.jobs:
                fn = getattr(inst, jm.method, None)
                if fn and inst._scheduler is not None:
                    spec = JobSpec(
                        id=jm.id, fn_name=jm.method,
                        interval_seconds=jm.interval_seconds,
                        run_on_activate=jm.run_on_activate,
                        enabled_feature=jm.enabled_feature,
                    )
                    inst._scheduler.start_job(spec, fn)

        # Track as ready and emit lifecycle pulse
        ready_set.add(name)
        await bus.emit_channel("llming:started", {"name": name})

    # Wire command registry for ConnectorBase instances (legacy)
    from hort.ext.connectors import CommandRegistry, ConnectorBase, SYSTEM_COMMANDS
    cmd_registry = CommandRegistry()
    _global_cmd_registry[0] = cmd_registry
    cmd_registry.register_system(SYSTEM_COMMANDS)
    for name, inst in registry._instances.items():
        if isinstance(inst, Llming) and not isinstance(inst, ConnectorBase):
            commands = inst.get_connector_commands()
            if commands:
                cmd_registry.register_llming(name, inst, commands)

    # Start ConnectorBase instances in background
    for name, inst in registry._instances.items():
        if isinstance(inst, ConnectorBase):
            inst.set_command_registry(cmd_registry)

            async def _start_bg(n: str, c: Any) -> None:
                try:
                    await c.start()
                    logger.info("Started connector: %s", n)
                except Exception as e:
                    logger.error("Failed to start connector %s: %s", n, e)
            asyncio.create_task(_start_bg(name, inst))

    # Fire @on_ready handlers whose dependencies are all met
    for deps, handler in ready_waiters:
        if all(d in ready_set for d in deps):
            try:
                await handler()
            except Exception:
                logger.exception("on_ready handler failed")

    logger.info("Llmings started (%d instances, %d commands registered)", len(ready_set), len(cmd_registry._commands) if hasattr(cmd_registry, '_commands') else 0)

    # Apply power settings from config
    try:
        apply_power_settings()
    except Exception:
        pass

    # Fire initial ticks so @on("tick:slow") etc. get data immediately
    import time
    now = time.time()
    await bus.emit_channel("tick:10hz", {"ts": now})
    await bus.emit_channel("tick:1hz", {"ts": now})
    await bus.emit_channel("tick:slow", {"ts": now})

    # Start built-in tick channels in background
    asyncio.create_task(_tick_loop(bus))


async def _tick_loop(bus: Any) -> None:
    """Emit built-in tick channels."""
    import asyncio
    import time

    counter = 0
    interval = 1.0 / 10  # 10 Hz base

    while True:
        await asyncio.sleep(interval)
        counter += 1
        now = time.time()

        # tick:10hz — every tick (100ms)
        await bus.emit_channel("tick:10hz", {"ts": now})

        # tick:1hz — every 10th tick
        if counter % 10 == 0:
            await bus.emit_channel("tick:1hz", {"ts": now})

        # tick:slow — every 50th tick (5s)
        if counter % 50 == 0:
            await bus.emit_channel("tick:slow", {"ts": now})


_global_cmd_registry: list = [None]  # mutable container for the singleton


def get_command_registry():
    """Get the global command registry (available after llming startup)."""
    return _global_cmd_registry[0]


# Backward-compatible alias
start_plugins = start_llmings


async def stop_llmings(registry: ExtensionRegistry) -> None:  # pragma: no cover
    """Stop all llmings cleanly. Called from shutdown event."""
    from hort.llming.base import Llming
    from hort.llming.bus import MessageBus
    from hort.llming.pulse import PulseBus

    bus = PulseBus.get()

    for name, inst in registry._instances.items():
        if not isinstance(inst, Llming):
            continue

        # Emit lifecycle pulse before stopping
        try:
            await bus.emit_channel("llming:stopped", {"name": name})
        except Exception:
            pass

        # Stop ConnectorBase instances (legacy)
        from hort.ext.connectors import ConnectorBase
        if isinstance(inst, ConnectorBase) and hasattr(inst, "stop"):
            try:
                await inst.stop()
            except Exception as e:
                logger.error("Error stopping %s: %s", name, e)

        if inst._scheduler is not None:
            inst._scheduler.stop_all()
        inst.deactivate()
        MessageBus.get().unregister(name)
        bus.clear_instance(name)

    logger.info("Llmings stopped")


# Backward-compatible alias
stop_plugins = stop_llmings


_caffeinate_proc: Any = None


def apply_power_settings() -> None:  # pragma: no cover
    """Apply caffeinate/display settings from config. Called on startup and on change."""
    import subprocess
    import sys

    if sys.platform != "darwin":
        return

    global _caffeinate_proc
    from hort.config import get_store

    cfg = get_store().get("general")

    # Caffeinate
    if cfg.get("caffeinate"):
        if _caffeinate_proc is None or _caffeinate_proc.poll() is not None:
            _caffeinate_proc = subprocess.Popen(
                ["caffeinate", "-d", "-i", "-s"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            logger.info("Caffeinate started (pid %d)", _caffeinate_proc.pid)
    else:
        if _caffeinate_proc and _caffeinate_proc.poll() is None:
            _caffeinate_proc.terminate()
            logger.info("Caffeinate stopped")
            _caffeinate_proc = None

    # Display sleep
    if cfg.get("display_sleep_disabled"):
        subprocess.run(["pmset", "-a", "displaysleep", "0"], capture_output=True)
        logger.info("Display sleep disabled")
    else:
        subprocess.run(["pmset", "-a", "displaysleep", "10"], capture_output=True)


def _register_llming_routes(app: FastAPI, registry: ExtensionRegistry) -> None:
    """Register llming REST API endpoints (admin/external use, auth-gated).

    The SPA uses WebSocket commands (llmings.list, config.get, etc.) instead.
    These REST endpoints are kept for admin tooling and future API access.
    """
    from fastapi import APIRouter

    # Build all routes on a router, then mount at both prefixes
    r = APIRouter()

    @r.get("")
    async def list_plugins() -> Response:
        """List all discovered llmings with status, features, and UI scripts."""
        plugins = registry.list_llmings()
        # Add UI script URLs for the frontend to load
        for p in plugins:
            manifest = registry.get_manifest(p["name"])
            if manifest and manifest.ui_script:
                p["ui_script_url"] = f"/ext/{manifest.name.replace('-', '_')}/static/{manifest.ui_script.replace('static/', '')}"
            else:
                p["ui_script_url"] = ""
        return Response(
            content=json.dumps(plugins), media_type="application/json"
        )

    @r.post("/{llming_id}/features/{feature}")
    async def toggle_feature(llming_id: str, feature: str, request: Request) -> Response:
        """Toggle a llming feature at runtime.

        Feature toggles are not yet supported in Llming — returns 404.
        """
        return Response(
            content=json.dumps({"error": "Feature toggles not available"}),
            media_type="application/json", status_code=404,
        )

    @r.post("/{llming_id}/unload")
    async def unload_plugin(llming_id: str) -> Response:
        """Hot-unload a llming."""
        ok = registry.unload_extension(llming_id)
        return Response(
            content=json.dumps({"ok": ok}), media_type="application/json",
            status_code=200 if ok else 404,
        )

    @app.post("/api/system/apply-power")
    async def apply_power() -> Response:
        """Apply power settings (caffeinate, display sleep) from config."""
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, apply_power_settings)
        return Response(content=json.dumps({"ok": True}), media_type="application/json")

    @r.get("/{llming_id}/status")
    async def llming_status(llming_id: str) -> Response:
        """Get llming's in-memory pulse (no disk I/O)."""
        inst = registry.get_instance(llming_id)
        if inst is None:
            return Response(
                content=json.dumps({"error": "Llming not found"}),
                media_type="application/json", status_code=404,
            )
        status: dict[str, Any] = {}
        if hasattr(inst, "get_pulse"):
            try:
                status = inst.get_pulse()
            except Exception:
                pass
        return Response(
            content=json.dumps(status, default=str), media_type="application/json"
        )

    @r.get("/{llming_id}/store")
    async def plugin_store(llming_id: str) -> Response:
        """Read a llming's store (for debugging / admin)."""
        from hort.llming.base import Llming

        store = None
        inst = registry.get_instance(llming_id)
        if isinstance(inst, Llming) and inst._store is not None:
            store = inst._store
        if store is None:
            return Response(
                content=json.dumps({"error": "Llming not found"}),
                media_type="application/json", status_code=404,
            )
        keys = await store.list_keys()
        items: dict[str, Any] = {}
        for k in keys[:100]:
            items[k] = await store.get(k)
        return Response(
            content=json.dumps(items, default=str), media_type="application/json"
        )

    # ── Credential management ────────────────────────────────────
    # These endpoints let the UI (including remote/mobile via cloud proxy)
    # manage authentication for Llmings that need external service access.

    @r.get("/{llming_id}/auth")
    async def get_auth_status(llming_id: str) -> Response:
        """Get auth status for a llming (no secrets exposed)."""
        inst = registry.get_instance(llming_id)
        if inst is None:
            return Response(
                content=json.dumps({"error": "Llming not found"}),
                media_type="application/json", status_code=404,
            )
        from hort.ext.credentials import CredentialStore
        creds = getattr(inst, "creds", None)
        if not isinstance(creds, CredentialStore):
            return Response(
                content=json.dumps({"auth_required": False}),
                media_type="application/json",
            )
        return Response(
            content=json.dumps({"auth_required": True, **creds.status_dict()}),
            media_type="application/json",
        )

    @r.post("/{llming_id}/auth/token")
    async def store_auth_token(llming_id: str, request: Request) -> Response:
        """Store a credential/token for a llming. Called after OAuth callback or manual entry."""
        inst = registry.get_instance(llming_id)
        if inst is None:
            return Response(
                content=json.dumps({"error": "Llming not found"}),
                media_type="application/json", status_code=404,
            )
        from hort.ext.credentials import CredentialStore
        creds = getattr(inst, "creds", None)
        if not isinstance(creds, CredentialStore):
            return Response(
                content=json.dumps({"error": "Llming does not use credentials"}),
                media_type="application/json", status_code=400,
            )
        data = await request.json()
        await creds.set_token(
            token=data.get("token", data),
            account_name=data.get("account_name", ""),
            expires_at=data.get("expires_at", 0.0),
        )
        return Response(
            content=json.dumps({"ok": True, **creds.status_dict()}),
            media_type="application/json",
        )

    @r.delete("/{llming_id}/auth")
    async def revoke_auth(llming_id: str) -> Response:
        """Clear stored credentials for a llming (logout)."""
        inst = registry.get_instance(llming_id)
        if inst is None:
            return Response(
                content=json.dumps({"error": "Llming not found"}),
                media_type="application/json", status_code=404,
            )
        from hort.ext.credentials import CredentialStore
        creds = getattr(inst, "creds", None)
        if not isinstance(creds, CredentialStore):
            return Response(
                content=json.dumps({"error": "Llming does not use credentials"}),
                media_type="application/json", status_code=400,
            )
        await creds.clear()
        return Response(
            content=json.dumps({"ok": True, **creds.status_dict()}),
            media_type="application/json",
        )

    # ── OAuth 2.0 browser flow ───────────────────────────────────

    @r.get("/{llming_id}/auth/oauth-start")
    async def oauth_start(llming_id: str, request: Request) -> Response:
        """Get the OAuth authorization URL (localhost only).

        OAuth callback flow is restricted to localhost for security.
        Remote access (cloud proxy) must use device code flow instead
        to prevent multi-tenant callback interception.
        """
        inst = registry.get_instance(llming_id)
        if inst is None:
            return Response(content=json.dumps({"error": "Not found"}), media_type="application/json", status_code=404)
        from hort.ext.credentials import CredentialStore
        creds = getattr(inst, "creds", None)
        if not isinstance(creds, CredentialStore):
            return Response(content=json.dumps({"error": "No credentials"}), media_type="application/json", status_code=400)

        # Security: OAuth callback only allowed on localhost
        host = request.headers.get("host", "")
        if not host.startswith("localhost") and not host.startswith("127.0.0.1"):
            return Response(
                content=json.dumps({"error": "OAuth callback only available on localhost. Use device code flow for remote access."}),
                media_type="application/json", status_code=403,
            )

        base = str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/auth/callback"

        auth_url = creds.get_auth_url(redirect_uri)
        if not auth_url:
            return Response(content=json.dumps({"error": "OAuth not configured"}), media_type="application/json", status_code=400)

        return Response(
            content=json.dumps({"auth_url": auth_url, "redirect_uri": redirect_uri}),
            media_type="application/json",
        )

    @app.get("/auth/callback")
    async def oauth_callback(request: Request) -> Response:
        """OAuth callback — provider redirects here with code + state."""
        from starlette.responses import HTMLResponse
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        error = request.query_params.get("error", "")

        if error:
            return HTMLResponse(f"<h2>Auth failed</h2><p>{error}</p>", status_code=400)

        if not code or not state:
            return HTMLResponse("<h2>Missing code or state</h2>", status_code=400)

        # Find the llming with the matching pending state
        from hort.ext.credentials import CredentialStore
        for name in list(registry._instances.keys()):
            inst = registry.get_instance(name)
            creds = getattr(inst, "creds", None) if inst else None
            if isinstance(creds, CredentialStore) and creds.validate_state(state):
                base = str(request.base_url).rstrip("/")
                redirect_uri = f"{base}/auth/callback"
                ok = await creds.exchange_code(code, redirect_uri)
                if ok:
                    return HTMLResponse(
                        f"<h2>Connected!</h2><p>{name} authenticated successfully.</p>"
                        "<p>You can close this tab.</p>",
                    )
                return HTMLResponse(f"<h2>Auth failed</h2><p>Token exchange failed for {name}.</p>", status_code=500)

        return HTMLResponse("<h2>Invalid state</h2><p>Auth session expired. Try again.</p>", status_code=400)

    # ── Device code flow ─────────────────────────────────────────

    @r.post("/{llming_id}/auth/device-start")
    async def device_code_start(llming_id: str) -> Response:
        """Start device code flow. Returns user_code and verification_uri."""
        inst = registry.get_instance(llming_id)
        if inst is None:
            return Response(content=json.dumps({"error": "Not found"}), media_type="application/json", status_code=404)
        from hort.ext.credentials import CredentialStore
        creds = getattr(inst, "creds", None)
        if not isinstance(creds, CredentialStore):
            return Response(content=json.dumps({"error": "No credentials"}), media_type="application/json", status_code=400)

        result = await creds.start_device_code()
        if result is None:
            return Response(content=json.dumps({"error": "Device code not supported"}), media_type="application/json", status_code=400)

        return Response(content=json.dumps(result), media_type="application/json")

    @r.post("/{llming_id}/auth/device-poll")
    async def device_code_poll(llming_id: str) -> Response:
        """Poll for device code completion. Returns {complete: true/false}."""
        inst = registry.get_instance(llming_id)
        if inst is None:
            return Response(content=json.dumps({"error": "Not found"}), media_type="application/json", status_code=404)
        from hort.ext.credentials import CredentialStore
        creds = getattr(inst, "creds", None)
        if not isinstance(creds, CredentialStore):
            return Response(content=json.dumps({"error": "No credentials"}), media_type="application/json", status_code=400)

        complete = await creds.poll_device_code()
        result = {"complete": complete}
        if complete:
            result.update(creds.status_dict())
        return Response(content=json.dumps(result), media_type="application/json")

    app.include_router(r, prefix="/api/llmings")
