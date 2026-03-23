"""Plugin management — discovery, loading, scheduling, and API routes.

Extracted from app.py to keep files focused. Called by ``create_app()``
to wire plugins into the FastAPI application.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response

from hort.ext.registry import ExtensionRegistry

logger = logging.getLogger("hort.plugins")

EXTENSIONS_DIR = Path(__file__).parent / "extensions"


def setup_plugins(app: FastAPI) -> ExtensionRegistry:
    """Discover plugins and register API routes. Returns the registry.

    Call this during ``create_app()``. The actual loading happens
    in the startup event (needs a running event loop for schedulers).
    """
    registry = ExtensionRegistry()
    registry.set_app(app)
    if EXTENSIONS_DIR.exists():
        registry.discover(EXTENSIONS_DIR)
    app.state.plugin_registry = registry
    _register_plugin_routes(app, registry)
    return registry


def load_plugins_sync(registry: ExtensionRegistry) -> None:  # pragma: no cover
    """Load compatible plugins synchronously (no scheduler start — call start_schedulers separately)."""
    registry.load_compatible()
    loaded = list(registry._instances.keys())
    logger.info("Loaded %d plugins: %s", len(loaded), loaded)


async def start_plugins(registry: ExtensionRegistry) -> None:  # pragma: no cover
    """Start plugin schedulers and connectors. Called once from startup event."""
    from hort.ext.plugin import PluginBase
    from hort.ext.scheduler import JobSpec, ScheduledMixin

    # Start schedulers
    for name, inst in registry._instances.items():
        if not isinstance(inst, PluginBase):
            continue
        manifest = registry.get_manifest(name)
        if not manifest:
            continue
        jobs: list[JobSpec] = []
        for jm in manifest.jobs:
            jobs.append(JobSpec(
                id=jm.id, fn_name=jm.method,
                interval_seconds=jm.interval_seconds,
                run_on_activate=False,
                enabled_feature=jm.enabled_feature,
            ))
        if isinstance(inst, ScheduledMixin):
            jobs.extend(inst.get_jobs())
        ctx = registry._contexts.get(name)
        if not ctx:
            continue
        for job in jobs:
            if job.enabled_feature and not ctx.config.is_feature_enabled(
                job.enabled_feature
            ):
                continue
            fn = getattr(inst, job.fn_name, None)
            if fn:
                ctx.scheduler.start_job(job, fn)
    logger.info("Plugin schedulers started")

    # Start messaging connectors (Telegram, etc.)
    await _start_connectors(registry)

    # Apply power settings from config on startup
    try:
        apply_power_settings()
    except Exception:
        pass


async def stop_plugins(registry: ExtensionRegistry) -> None:  # pragma: no cover
    """Stop connectors and schedulers cleanly. Called from shutdown event."""
    from hort.ext.connectors import ConnectorBase

    for name, inst in registry._instances.items():
        if isinstance(inst, ConnectorBase):
            try:
                await inst.stop()
                logger.info("Stopped connector: %s", name)
            except Exception as e:
                logger.error("Error stopping connector %s: %s", name, e)

    # Stop all schedulers
    for name, ctx in registry._contexts.items():
        if ctx and ctx.scheduler:
            ctx.scheduler.stop_all()
    logger.info("Plugins stopped")


async def _start_connectors(registry: ExtensionRegistry) -> None:  # pragma: no cover
    """Discover and start messaging connectors with command registry."""
    logger.info("Starting connector discovery...")
    from hort.ext.connectors import CommandRegistry, ConnectorBase, ConnectorMixin

    cmd_registry = CommandRegistry()

    # Register system commands
    from hort.extensions.core.telegram_connector.provider import SYSTEM_COMMANDS
    cmd_registry.register_system(SYSTEM_COMMANDS)

    # Collect commands from plugins
    for name, inst in registry._instances.items():
        if isinstance(inst, ConnectorMixin) and not isinstance(inst, ConnectorBase):
            commands = inst.get_connector_commands()
            if commands:
                cmd_registry.register_plugin(name, inst, commands)
                logger.info("Registered %d commands from %s", len(commands), name)

    # Start connectors
    for name, inst in registry._instances.items():
        if isinstance(inst, ConnectorBase):
            inst.set_command_registry(cmd_registry)
            try:
                await inst.start()
                logger.info("Started connector: %s", name)
            except Exception as e:
                logger.error("Failed to start connector %s: %s", name, e)


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


def _register_plugin_routes(app: FastAPI, registry: ExtensionRegistry) -> None:
    """Register plugin-related API endpoints on the app."""

    @app.get("/api/plugins")
    async def list_plugins() -> Response:
        """List all discovered plugins with status, features, and UI scripts."""
        plugins = registry.list_plugins()
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

    @app.post("/api/plugins/{plugin_id}/features/{feature}")
    async def toggle_feature(plugin_id: str, feature: str, request: Request) -> Response:
        """Toggle a plugin feature at runtime."""
        data = await request.json()
        enabled = data.get("enabled", True)
        ctx = registry._contexts.get(plugin_id)
        if ctx is None:
            return Response(
                content=json.dumps({"error": "Plugin not found"}),
                media_type="application/json", status_code=404,
            )
        ctx.config.set_feature(feature, enabled)
        return Response(
            content=json.dumps({"ok": True, "feature": feature, "enabled": enabled}),
            media_type="application/json",
        )

    @app.post("/api/plugins/{plugin_id}/unload")
    async def unload_plugin(plugin_id: str) -> Response:
        """Hot-unload a plugin."""
        ok = registry.unload_extension(plugin_id)
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

    @app.get("/api/plugins/{plugin_id}/status")
    async def plugin_status(plugin_id: str) -> Response:
        """Get plugin's in-memory status summary (no disk I/O)."""
        inst = registry.get_instance(plugin_id)
        if inst is None:
            return Response(
                content=json.dumps({"error": "Plugin not found"}),
                media_type="application/json", status_code=404,
            )
        # Call get_status() if the plugin has it, otherwise empty
        status: dict[str, Any] = {}
        if hasattr(inst, "get_status"):
            try:
                status = inst.get_status()
            except Exception:
                pass
        return Response(
            content=json.dumps(status, default=str), media_type="application/json"
        )

    @app.get("/api/plugins/{plugin_id}/store")
    async def plugin_store(plugin_id: str) -> Response:
        """Read a plugin's store (for debugging / admin)."""
        ctx = registry._contexts.get(plugin_id)
        if ctx is None:
            return Response(
                content=json.dumps({"error": "Plugin not found"}),
                media_type="application/json", status_code=404,
            )
        keys = await ctx.store.list_keys()
        items: dict[str, Any] = {}
        for k in keys[:100]:
            items[k] = await ctx.store.get(k)
        return Response(
            content=json.dumps(items, default=str), media_type="application/json"
        )
