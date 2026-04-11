"""WS commands for llming management — list, pulse, store, debug."""

from __future__ import annotations

from typing import Any

from llming_com import WSRouter

from hort.commands._registry import get_llming_registry

router = WSRouter(prefix="llmings")


@router.handler("list")
async def llmings_list(controller: Any) -> dict[str, Any]:
    """List all llmings with status and UI script URLs."""
    registry = get_llming_registry()
    if registry is None:
        return {"data": []}
    llmings = registry.list_llmings()
    for p in llmings:
        manifest = registry.get_manifest(p["name"])
        if manifest and manifest.ui_script:
            p["ui_script_url"] = (
                f"/ext/{manifest.name.replace('-', '_')}/static/"
                f"{manifest.ui_script.replace('static/', '')}"
            )
        else:
            p["ui_script_url"] = ""
    return {"data": llmings}


@router.handler("pulse")
async def llming_pulse(controller: Any, name: str) -> dict[str, Any]:
    """Get live pulse data for a single llming."""
    registry = get_llming_registry()
    if not registry:
        return {"name": name, "data": {}}
    inst = registry.get_instance(name)
    data: dict[str, Any] = {}
    if inst and hasattr(inst, "get_pulse"):
        try:
            data = inst.get_pulse()
        except Exception:
            pass
    return {"name": name, "data": data}


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
    """Deep debug info for a llming — class, config, powers, pulse, scheduler, credentials."""
    from hort.llming.base import Llming

    registry = get_llming_registry()
    if not registry:
        return {"error": "no registry"}

    if not name:
        # Return summary of ALL llmings
        summary = []
        for inst_name in sorted(registry._instances.keys()):
            inst = registry.get_instance(inst_name)
            info: dict[str, Any] = {"name": inst_name, "type": type(inst).__name__}
            if isinstance(inst, Llming):
                info["class_name"] = inst.class_name
                info["has_pulse"] = bool(inst.get_pulse())
                info["powers"] = [p.name for p in inst.get_powers()]
                info["scheduler_jobs"] = inst._scheduler.running_jobs if inst._scheduler else []
            summary.append(info)
        return {"data": summary}

    inst = registry.get_instance(name)
    if inst is None:
        return {"error": f"llming '{name}' not found"}

    info: dict[str, Any] = {
        "name": name,
        "type": type(inst).__name__,
    }
    if isinstance(inst, Llming):
        info["class_name"] = inst.class_name
        info["instance_name"] = inst.instance_name
        info["config"] = inst.config
        info["pulse"] = inst.get_pulse()
        info["powers"] = [{"name": p.name, "type": p.type.value} for p in inst.get_powers()]
        info["scheduler_jobs"] = inst._scheduler.running_jobs if inst._scheduler else []
        info["has_credentials"] = inst.credentials is not None
        info["soul_length"] = len(inst.soul) if inst.soul else 0
    return {"data": info}


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
