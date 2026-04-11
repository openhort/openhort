"""WS commands for the card API — pulse subscriptions, vault access, power calls.

Cards (JS) use these to interact with their llming and other permitted llmings.
All access is routed through the server — cards never talk to llmings directly.

Message types:
    card.subscribe   — subscribe to a pulse channel (server pushes events)
    card.unsubscribe — unsubscribe from a channel
    card.vault.read  — read from a vault (own or permitted other)
    card.vault.write — write to own vault
    card.power       — execute a power (own or permitted other)
    card.scrolls.query — query a scrolls collection
"""

from __future__ import annotations

import logging
from typing import Any

from llming_com import WSRouter

from hort.commands._registry import get_llming_registry

logger = logging.getLogger(__name__)

router = WSRouter(prefix="card")

# Per-session pulse subscriptions: {session_id: {channel: True}}
_viewer_subscriptions: dict[str, set[str]] = {}


@router.handler("subscribe")
async def card_subscribe(controller: Any, channel: str = "") -> dict[str, Any]:
    """Subscribe this viewer to a pulse channel. Server pushes events."""
    if not channel:
        return {"error": "channel required"}
    sid = getattr(controller, "session_id", "")
    if sid not in _viewer_subscriptions:
        _viewer_subscriptions[sid] = set()
    _viewer_subscriptions[sid].add(channel)
    return {"ok": True, "channel": channel}


@router.handler("unsubscribe")
async def card_unsubscribe(controller: Any, channel: str = "") -> dict[str, Any]:
    """Unsubscribe from a pulse channel."""
    sid = getattr(controller, "session_id", "")
    if sid in _viewer_subscriptions:
        _viewer_subscriptions[sid].discard(channel)
    return {"ok": True, "channel": channel}


@router.handler("vault.read")
async def card_vault_read(controller: Any, owner: str = "", key: str = "") -> dict[str, Any]:
    """Read from a vault. owner="" means own llming."""
    if not key:
        return {"error": "key required"}
    if not owner:
        return {"error": "owner required"}
    try:
        from hort.storage.store import StorageManager
        storage = StorageManager.get().get_storage(owner)
        result = storage.persist.scrolls.find_one("_kv", {"_key": key})
        if result is None:
            return {"data": {}}
        result.pop("_id", None)
        result.pop("_key", None)
        result.pop("_access", None)
        return {"data": result}
    except Exception as e:
        return {"error": str(e)}


@router.handler("vault.write")
async def card_vault_write(controller: Any, owner: str = "", key: str = "", data: dict | None = None) -> dict[str, Any]:
    """Write to own vault."""
    if not owner or not key or data is None:
        return {"error": "owner, key, and data required"}
    try:
        from hort.storage.store import StorageManager
        storage = StorageManager.get().get_storage(owner)
        data["_key"] = key
        storage.persist.scrolls.delete_one("_kv", {"_key": key})
        storage.persist.scrolls.insert("_kv", data)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@router.handler("power")
async def card_power(controller: Any, llming: str = "", power: str = "", args: dict | None = None) -> dict[str, Any]:
    """Execute a power on a llming."""
    if not llming or not power:
        return {"error": "llming and power required"}
    registry = get_llming_registry()
    if not registry:
        return {"error": "registry not available"}
    inst = registry.get_instance(llming)
    if inst is None:
        return {"error": f"llming '{llming}' not found"}
    try:
        result = await inst.execute_power(power, args or {})
        # Serialize Pydantic models
        if hasattr(result, "model_dump"):
            return {"result": result.model_dump()}
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}


@router.handler("scrolls.query")
async def card_scrolls_query(
    controller: Any, owner: str = "", collection: str = "",
    filter: dict | None = None, limit: int = 50,
) -> dict[str, Any]:
    """Query a scrolls collection."""
    if not owner or not collection:
        return {"error": "owner and collection required"}
    try:
        from hort.storage.store import StorageManager
        storage = StorageManager.get().get_storage(owner)
        results = storage.persist.scrolls.find(collection, filter or {}, limit=limit)
        return {"data": results}
    except Exception as e:
        return {"error": str(e)}


def get_viewer_subscriptions() -> dict[str, set[str]]:
    """Get all viewer pulse subscriptions. Used by the pulse push system."""
    return _viewer_subscriptions


def remove_viewer(session_id: str) -> None:
    """Clean up subscriptions when a viewer disconnects."""
    _viewer_subscriptions.pop(session_id, None)
