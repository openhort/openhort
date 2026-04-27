"""WS commands for llming management — list, store, debug, execute."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llming_com import WSRouter

from hort.commands._registry import get_llming_registry

_llmings_root = Path(__file__).parent.parent.parent / "llmings"


def _has_file(dir_name: str, filename: str) -> bool:
    """Check if a llming has a specific file."""
    for provider in _llmings_root.iterdir() if _llmings_root.is_dir() else []:
        if not provider.is_dir():
            continue
        ext = provider / dir_name
        if ext.is_dir():
            if (ext / filename).exists():
                return True
            # Also check app/index.vue for app routes
            if filename == "app.vue" and (ext / "app" / "index.vue").exists():
                return True
    return False

router = WSRouter(prefix="llmings")


@router.handler("list")
async def llmings_list(controller: Any) -> dict[str, Any]:
    """List all llmings with status and UI script URLs."""
    from hort.browser_isolation import load_browser_isolation_policy, should_isolate_widget

    registry = get_llming_registry()
    if registry is None:
        return {"data": [], "browser_isolation": load_browser_isolation_policy()}
    isolation_policy = load_browser_isolation_policy()
    llmings = registry.list_llmings()
    for p in llmings:
        manifest = registry.get_manifest(p["name"])
        dir_name = manifest.name.replace("-", "_") if manifest else p["name"].replace("-", "_")
        if manifest and manifest.ui_script:
            p["ui_script_url"] = f"/ext/{dir_name}/static/{manifest.ui_script.replace('static/', '')}"
        else:
            p["ui_script_url"] = ""
        # App script (app.vue / app/index.vue)
        p["app_script_url"] = f"/ext/{dir_name}/static/app.js" if _has_file(dir_name, "app.vue") else ""
        # Demo script
        p["demo_url"] = f"/ext/{dir_name}/demo.js" if _has_file(dir_name, "demo.js") else ""
        # Card sandbox: expose trust + needs so the host can stamp the
        # per-iframe capability table. Also infer ui_widgets from a
        # sibling <name>.vue or card.vue if the manifest didn't declare it
        # explicitly — the presence of the source file is what makes a
        # llming a card-bearing one. Without this, vue_loader-generated
        # cards would still load inline (defeating the sandbox).
        if manifest:
            p["trust"] = manifest.trust
            p["needs"] = manifest.needs
            p["browser_isolated"] = should_isolate_widget(manifest, isolation_policy)
            p["browser_isolation_hint"] = manifest.browser_isolation
            if manifest.local_quota_mb:
                p["local_quota_mb"] = manifest.local_quota_mb
            # vue_loader always emits a component named "<name>-card",
            # so when a .vue source exists we use that — overriding any
            # stale manifest declaration left over from earlier conversions.
            # Manifests without a .vue source keep whatever they declare
            # (they're hand-rolled cards.js with their own component names).
            if _has_file(dir_name, f"{dir_name}.vue") or _has_file(dir_name, "card.vue"):
                p["ui_widgets"] = [manifest.name.replace("_", "-") + "-card"]
        else:
            p["trust"] = "sandboxed"
            p["needs"] = {}
            p["browser_isolated"] = True
            p["browser_isolation_hint"] = ""
    return {"data": llmings, "browser_isolation": isolation_policy}


@router.handler("feature")
async def llming_feature(
    controller: Any, name: str = "", feature: str = "", enabled: bool = True
) -> dict[str, Any]:
    """Toggle a llming feature (stub — feature toggles not yet implemented)."""
    return {"name": name, "feature": feature, "ok": False, "error": "Feature toggles not available"}


@router.handler("store")
async def llming_store(controller: Any, name: str) -> dict[str, Any]:
    """Read store keys for a llming."""
    from hort.llming.base import Llming

    registry = get_llming_registry()
    inst = registry.get_instance(name) if registry else None
    items: dict[str, Any] = {}
    if isinstance(inst, Llming) and inst._store is not None:
        keys = await inst._store.list_keys()
        for k in keys[:100]:
            items[k] = await inst._store.get(k)
    return {"name": name, "data": items}


@router.handler("debug")
async def llming_debug(controller: Any, name: str = "") -> dict[str, Any]:
    """Deep debug info for a llming."""
    from hort.llming.base import Llming

    registry = get_llming_registry()
    if not registry:
        return {"error": "no registry"}

    if not name:
        summary = []
        for inst_name in sorted(registry._instances.keys()):
            inst = registry.get_instance(inst_name)
            summary_info: dict[str, Any] = {"name": inst_name, "type": type(inst).__name__}
            if isinstance(inst, Llming):
                summary_info["class_name"] = inst.class_name
                summary_info["powers"] = [p.name for p in inst.get_powers()]
                summary_info["scheduler_jobs"] = inst._scheduler.running_jobs if inst._scheduler else []
            summary.append(summary_info)
        return {"data": summary}

    inst = registry.get_instance(name)
    if inst is None:
        return {"error": f"llming '{name}' not found"}

    detail_info: dict[str, Any] = {
        "name": name,
        "type": type(inst).__name__,
    }
    if isinstance(inst, Llming):
        detail_info["class_name"] = inst.class_name
        detail_info["instance_name"] = inst.instance_name
        detail_info["config"] = inst.config
        detail_info["powers"] = [{"name": p.name, "type": p.type.value} for p in inst.get_powers()]
        detail_info["scheduler_jobs"] = inst._scheduler.running_jobs if inst._scheduler else []
        detail_info["has_credentials"] = inst.credentials is not None
        detail_info["soul_length"] = len(inst.soul) if inst.soul else 0
    return {"data": detail_info}


@router.handler("execute_power")
async def llming_execute_power(
    controller: Any, name: str = "", power: str = "", args: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute a power on a llming (for UI cards to call MCP tools)."""
    from hort.llming.base import Llming

    registry = get_llming_registry()
    if not registry:
        return {"error": "no registry"}
    inst = registry.get_instance(name)
    if inst is None:
        return {"error": f"llming '{name}' not found"}
    if not isinstance(inst, Llming):
        return {"error": f"'{name}' is not a Llming"}
    try:
        result = await inst.execute_power(power, args or {})
        return {"name": name, "power": power, "result": result}
    except Exception as e:
        return {"error": str(e)}
