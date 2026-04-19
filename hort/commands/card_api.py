"""WS commands for the card API — pulse subscriptions, vault access, power calls.

Cards (JS) use these to interact with their llming and other permitted llmings.
All access is routed through the server — cards never talk to llmings directly.

Message types:
    card.subscribe   — subscribe to a pulse channel (server pushes events)
    card.unsubscribe — unsubscribe from a channel
    card.vault.read  — read from a vault (own or permitted other)
    card.vault.write — write to own vault
    card.vault.watch — subscribe to vault key changes (server pushes updates)
    card.vault.unwatch — unsubscribe from vault key changes
    card.power       — execute a power (own or permitted other)
    card.scrolls.query — query a scrolls collection
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from llming_com import WSRouter

from hort.commands._registry import get_llming_registry

logger = logging.getLogger(__name__)

router = WSRouter(prefix="card")

# Per-session pulse subscriptions: {session_id: {channel}}
_viewer_subscriptions: dict[str, set[str]] = {}

# Per-session vault watchers: {session_id: {(owner, key)}}
_vault_watchers: dict[str, set[tuple[str, str]]] = {}


@router.handler("subscribe")
async def card_subscribe(controller: Any, channel: str = "") -> dict[str, Any]:
    """Subscribe this viewer to a pulse channel. Server pushes events."""
    if not channel:
        return {"error": "channel required"}
    sid = getattr(controller, "session_id", "")
    _viewer_subscriptions.setdefault(sid, set()).add(channel)
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
        # Notify watchers
        clean = dict(data)
        clean.pop("_key", None)
        notify_vault_change(owner, key, clean)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@router.handler("vault.watch")
async def card_vault_watch(controller: Any, owner: str = "", key: str = "") -> dict[str, Any]:
    """Subscribe to vault key changes. Server pushes updates."""
    if not owner or not key:
        return {"error": "owner and key required"}
    sid = getattr(controller, "session_id", "")
    _vault_watchers.setdefault(sid, set()).add((owner, key))
    # Return current value immediately
    try:
        from hort.storage.store import StorageManager
        storage = StorageManager.get().get_storage(owner)
        result = storage.persist.scrolls.find_one("_kv", {"_key": key})
        if result:
            result.pop("_id", None)
            result.pop("_key", None)
            result.pop("_access", None)
            return {"ok": True, "data": result}
    except Exception:
        pass
    return {"ok": True, "data": {}}


@router.handler("vault.unwatch")
async def card_vault_unwatch(controller: Any, owner: str = "", key: str = "") -> dict[str, Any]:
    """Unsubscribe from vault key changes."""
    sid = getattr(controller, "session_id", "")
    if sid in _vault_watchers:
        _vault_watchers[sid].discard((owner, key))
    return {"ok": True}


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


# ---- Viewer subscription accessors ----


def get_viewer_subscriptions() -> dict[str, set[str]]:
    """Get all viewer pulse subscriptions. Used by the pulse push system."""
    return _viewer_subscriptions


def remove_viewer(session_id: str) -> None:
    """Clean up all subscriptions when a viewer disconnects."""
    _viewer_subscriptions.pop(session_id, None)
    _vault_watchers.pop(session_id, None)
    # Also clean up stream subscriptions
    try:
        from hort.llming.stream_bus import StreamBus
        StreamBus.get().remove_subscriber_from_all(session_id)
    except Exception:
        pass


# ---- Stream handlers ----


@router.handler("stream.subscribe")
async def card_stream_subscribe(controller: Any, channel: str = "", **params: Any) -> dict[str, Any]:
    """Subscribe to a stream channel. Producer is notified of new subscriber."""
    if not channel:
        return {"error": "channel required"}
    sid: str = getattr(controller, "session_id", "")
    try:
        from hort.llming.stream_bus import StreamBus
        bus = StreamBus.get()
        # Auto-declare on subscribe (producer may declare later or not at all)
        handle = bus.declare(channel)
        await handle.add_subscriber(sid, params)
        return {"ok": True, "channel": channel}
    except Exception as e:
        return {"error": str(e)}


@router.handler("stream.unsubscribe")
async def card_stream_unsubscribe(controller: Any, channel: str = "") -> dict[str, Any]:
    """Unsubscribe from a stream channel."""
    sid: str = getattr(controller, "session_id", "")
    try:
        from hort.llming.stream_bus import StreamBus
        handle = StreamBus.get().get_channel(channel)
        if handle:
            await handle.remove_subscriber(sid)
    except Exception:
        pass
    return {"ok": True}


@router.handler("stream.ack")
async def card_stream_ack(controller: Any, channel: str = "") -> dict[str, Any]:
    """ACK from viewer — ready for next frame on this stream."""
    sid: str = getattr(controller, "session_id", "")
    try:
        from hort.llming.stream_bus import StreamBus
        handle = StreamBus.get().get_channel(channel)
        if handle:
            handle.ack(sid)
    except Exception:
        pass
    return {"ok": True}


# ---- Stream delivery ----


async def push_stream_frame(channel: str, session_ids: list[str], data: Any) -> None:
    """Push a frame to specific viewer sessions (frame-mode stream)."""
    try:
        from hort.session import HortRegistry
        registry = HortRegistry.get()
        msg: dict[str, Any] = {"type": "stream.frame", "channel": channel, "data": data}
        for sid in session_ids:
            try:
                entry = registry.get_session(sid)
                if entry and hasattr(entry, "controller") and entry.controller:
                    await entry.controller.send(msg)
            except Exception:
                pass
    except Exception:
        pass


async def push_stream_chunk(channel: str, session_ids: list[str], chunk: Any) -> None:
    """Push a chunk to all subscribers (continuous-mode stream)."""
    try:
        from hort.session import HortRegistry
        registry = HortRegistry.get()
        msg: dict[str, Any] = {"type": "stream.chunk", "channel": channel, "data": chunk}
        for sid in session_ids:
            try:
                entry = registry.get_session(sid)
                if entry and hasattr(entry, "controller") and entry.controller:
                    await entry.controller.send(msg)
            except Exception:
                pass
    except Exception:
        pass


# ---- Vault change push (throttled) ----

_VAULT_PUSH_MIN_INTERVAL = 0.2  # 200ms → 5Hz max per (owner, key)
_vault_last_push: dict[tuple[str, str], float] = {}
_vault_pending_data: dict[tuple[str, str], dict[str, Any]] = {}
_vault_pending_handle: dict[tuple[str, str], asyncio.TimerHandle] = {}


def notify_vault_change(owner: str, key: str, data: dict[str, Any]) -> None:
    """Push vault update to watching viewers, throttled to 5Hz max.

    Called by Vault.set(). If writes happen faster than 5Hz, only the
    latest value is pushed at the next throttle window.
    """
    if not _vault_watchers:
        return

    wk = (owner, key)
    now = time.monotonic()
    last = _vault_last_push.get(wk, 0)
    elapsed = now - last

    if elapsed >= _VAULT_PUSH_MIN_INTERVAL:
        # Push immediately
        _vault_last_push[wk] = now
        _push_vault_to_viewers(owner, key, data)
        # Cancel any pending delayed push
        handle = _vault_pending_handle.pop(wk, None)
        if handle:
            handle.cancel()
        _vault_pending_data.pop(wk, None)
    else:
        # Store latest data, schedule push at next window
        _vault_pending_data[wk] = data
        if wk not in _vault_pending_handle:
            delay = _VAULT_PUSH_MIN_INTERVAL - elapsed
            try:
                loop = asyncio.get_running_loop()
                _vault_pending_handle[wk] = loop.call_later(
                    delay, _flush_vault_push, owner, key
                )
            except RuntimeError:
                pass


def _flush_vault_push(owner: str, key: str) -> None:
    """Delayed push — sends the latest stored data."""
    wk = (owner, key)
    _vault_pending_handle.pop(wk, None)
    data = _vault_pending_data.pop(wk, None)
    if data is not None:
        _vault_last_push[wk] = time.monotonic()
        _push_vault_to_viewers(owner, key, data)


def _push_vault_to_viewers(owner: str, key: str, data: dict[str, Any]) -> None:
    """Send vault.update to all watching viewer sessions."""
    try:
        from hort.session import HortRegistry
        registry = HortRegistry.get()
        msg = {"type": "vault.update", "owner": owner, "key": key, "data": data}

        for sid, watches in _vault_watchers.items():
            if (owner, key) not in watches:
                continue
            try:
                entry = registry.get_session(sid)
                if entry and hasattr(entry, "controller") and entry.controller:
                    asyncio.create_task(entry.controller.send(msg))
            except Exception:
                pass
    except Exception:
        pass  # Registry not ready during startup
