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
    """Start plugin schedulers. Called from FastAPI startup event.

    Deferred: schedulers start 3s after startup to avoid blocking the event loop.
    """
    import asyncio
    from hort.ext.plugin import PluginBase
    from hort.ext.scheduler import JobSpec, ScheduledMixin

    async def _deferred_start() -> None:
        await asyncio.sleep(3)  # let server finish startup first
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

    asyncio.create_task(_deferred_start())


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
