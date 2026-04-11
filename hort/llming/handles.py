"""Dict-like accessors for cross-llming communication.

    self.vault.set("state", {"connected": True})       # own vault
    self.vault.get("state", default={})                 # own vault
    self.vaults["system-monitor"].get("state")          # other's vault (read-only)
    self.llmings["hue-bridge"].call("set_light", {...}) # cross-llming power
    self.channels["cpu_spike"].subscribe(handler)        # pulse channel
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from pydantic import BaseModel

if TYPE_CHECKING:
    from hort.llming.bus import MessageBus
    from hort.llming.pulse import PulseBus

logger = logging.getLogger(__name__)


# ── Vault (own — read/write, cached) ──


class Vault:
    """Own vault — read/write with local cache.

    Backed by ScrollStore. Cached in-memory for fast reads.
    On set(), writes to storage and invalidates cache.

    Usage::

        self.vault.set("state", {"connected": True})
        self.vault.set("cache", data, ttl=300)
        data = self.vault.get("state", default={})
        self.vault.delete("state")
    """

    def __init__(self, owner: str) -> None:
        self._owner = owner
        self._cache: dict[str, dict[str, Any]] = {}

    def _scrolls(self) -> Any:
        from hort.storage.store import StorageManager
        return StorageManager.get().get_storage(self._owner).persist.scrolls

    def get(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read a key. Returns cached value or fetches from storage."""
        if key in self._cache:
            return self._cache[key]
        try:
            result = self._scrolls().find_one("_kv", {"_key": key})
            if result is None:
                return default if default is not None else {}
            result.pop("_id", None)
            result.pop("_key", None)
            result.pop("_access", None)
            self._cache[key] = result
            return result
        except Exception:
            return default if default is not None else {}

    def set(self, key: str, data: dict[str, Any] | BaseModel, *, ttl: int | None = None) -> None:
        """Write a key. Updates cache and storage."""
        payload = data.model_dump() if isinstance(data, BaseModel) else dict(data)
        payload["_key"] = key
        try:
            scrolls = self._scrolls()
            scrolls.delete_one("_kv", {"_key": key})
            scrolls.insert("_kv", payload, ttl=ttl)
        except Exception:
            logger.debug("Vault set failed: %s/%s", self._owner, key)
        # Update cache (strip internal fields)
        cached = dict(payload)
        cached.pop("_key", None)
        self._cache[key] = cached

    def delete(self, key: str) -> bool:
        """Delete a key from vault and cache."""
        self._cache.pop(key, None)
        try:
            result = self._scrolls().delete_one("_kv", {"_key": key})
            return result.get("deleted", 0) > 0
        except Exception:
            return False

    def query(self, collection: str, filter: dict[str, Any] | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        """Query a scrolls collection in own vault."""
        try:
            return self._scrolls().find(collection, filter or {}, limit=limit)
        except Exception:
            return []


# ── VaultHandle (other llming — read-only) ──


class VaultHandle:
    """Read-only access to another llming's vault.

    Usage::

        data = self.vaults["system-monitor"].get("state")
        entries = self.vaults["system-monitor"].query("history", {"cpu": {"$gt": 90}})
    """

    def __init__(self, owner: str) -> None:
        self._owner = owner

    def get(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read a key from the other llming's vault."""
        from hort.storage.store import StorageManager
        try:
            storage = StorageManager.get().get_storage(self._owner)
            result = storage.persist.scrolls.find_one("_kv", {"_key": key})
            if result is None:
                return default if default is not None else {}
            result.pop("_id", None)
            result.pop("_key", None)
            result.pop("_access", None)
            return result
        except Exception:
            return default if default is not None else {}

    def query(self, collection: str, filter: dict[str, Any] | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        """Query a scrolls collection in the other llming's vault."""
        from hort.storage.store import StorageManager
        try:
            storage = StorageManager.get().get_storage(self._owner)
            return storage.persist.scrolls.find(collection, filter or {}, limit=limit)
        except Exception:
            return []


class VaultHandleMap:
    """Dict-like access to other llmings' vaults: ``self.vaults["name"]``."""

    def __init__(self, reader: str) -> None:
        self._reader = reader

    def __getitem__(self, owner: str) -> VaultHandle:
        return VaultHandle(owner)


# ── Llming Handle ──


class LlmingHandle:
    """Proxy for calling another llming's powers.

    Usage::

        result = await self.llmings["system-monitor"].call("get_metrics")
    """

    def __init__(self, target: str, source: str, bus: MessageBus) -> None:
        self._target = target
        self._source = source
        self._bus = bus

    async def call(self, power: str, args: dict[str, Any] | None = None) -> Any:
        return await self._bus.call(
            source=self._source,
            target=self._target,
            power=power,
            args=args or {},
        )


class LlmingHandleMap:
    """Dict-like access to other llmings: ``self.llmings["name"]``."""

    def __init__(self, source: str, bus: MessageBus) -> None:
        self._source = source
        self._bus = bus

    def __getitem__(self, target: str) -> LlmingHandle:
        return LlmingHandle(target, self._source, self._bus)


# ── Channel Handle ──


PulseHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class ChannelHandle:
    """Handle for a named pulse channel.

    Usage::

        self.channels["cpu_spike"].subscribe(self.on_spike)
    """

    def __init__(self, channel: str, bus: PulseBus) -> None:
        self._channel = channel
        self._bus = bus

    def subscribe(self, handler: PulseHandler) -> None:
        self._bus.subscribe_channel(self._channel, handler)

    def unsubscribe(self, handler: PulseHandler) -> None:
        self._bus.unsubscribe_channel(self._channel, handler)


class ChannelHandleMap:
    """Dict-like access to pulse channels: ``self.channels["name"]``."""

    def __init__(self, bus: PulseBus) -> None:
        self._bus = bus

    def __getitem__(self, channel: str) -> ChannelHandle:
        return ChannelHandle(channel, self._bus)
