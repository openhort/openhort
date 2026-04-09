"""WS commands for config management."""

from __future__ import annotations

from typing import Any

from llming_com import WSRouter

router = WSRouter(prefix="config")


@router.handler("get")
async def config_get(controller: Any, section: str = "") -> dict[str, Any]:
    """Get a config section."""
    from hort.config import get_store
    store = get_store()
    data = store.get(section) if section else {}
    return {"section": section, "data": data or {}}


@router.handler("set")
async def config_set(controller: Any, section: str = "", data: dict | None = None) -> dict[str, Any]:
    """Update a config section (merge)."""
    from hort.config import get_store
    if section and isinstance(data, dict):
        store = get_store()
        existing = store.get(section) or {}
        existing.update(data)
        store.set(section, existing)
    return {"section": section, "ok": True}
