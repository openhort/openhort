"""WS commands for llming management — list, pulse, store."""

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
    from hort.llming.base import LlmingBase

    registry = get_llming_registry()
    inst = registry.get_instance(name) if registry else None
    items: dict[str, Any] = {}
    if isinstance(inst, LlmingBase) and inst._store is not None:
        keys = await inst._store.list_keys()
        for k in keys[:100]:
            items[k] = await inst._store.get(k)
    return {"name": name, "data": items}
