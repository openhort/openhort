"""Vault, llming, and channel handles.

    self.vault.set("state", {"connected": True})
    self.vault.get("state")
    self.vault.put_file("exports", "report.pdf", pdf_bytes)
    data, info = self.vault.get_file("exports", "report.pdf")

    self.vaults["system-monitor"].get("state")

    await self.llmings["hue-bridge"].call("set_light", {...})

    self.channels["cpu_spike"].subscribe(handler)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from pydantic import BaseModel

if TYPE_CHECKING:
    from hort.llming.bus import MessageBus
    from hort.llming.pulse import PulseBus

logger = logging.getLogger(__name__)


# ── Vault (own — full access, cached) ──


class Vault:
    """Own vault — key-value data + binary files, locally cached.

    Data (scrolls):
        self.vault.set("state", {"connected": True}, ttl=3600)
        data = self.vault.get("state", default={})
        self.vault.delete("state")
        results = self.vault.query("history", {"cpu": {"$gt": 90}}, limit=20)
        self.vault.insert("history", {"cpu": 42, "ts": time.time()})

    Files (crates):
        self.vault.put_file("exports", "report.pdf", pdf_bytes)
        data, info = self.vault.get_file("exports", "report.pdf")
        self.vault.delete_file("exports", "report.pdf")
        files = self.vault.list_files("exports")
    """

    def __init__(self, owner: str) -> None:
        self._owner = owner
        self._cache: dict[str, dict[str, Any]] = {}

    def _storage(self) -> Any:
        from hort.storage.store import StorageManager
        return StorageManager.get().get_storage(self._owner).persist

    # ── Key-value (scrolls) ──

    def get(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read a key. Cached locally for fast repeated reads."""
        if key in self._cache:
            return self._cache[key]
        try:
            result = self._storage().scrolls.find_one("_kv", {"_key": key})
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
        """Write a key. TTL in seconds (None = permanent)."""
        payload = data.model_dump() if isinstance(data, BaseModel) else dict(data)
        payload["_key"] = key
        try:
            scrolls = self._storage().scrolls
            scrolls.delete_one("_kv", {"_key": key})
            scrolls.insert("_kv", payload, ttl=ttl)
        except Exception:
            logger.debug("Vault set failed: %s/%s", self._owner, key)
        cached = dict(payload)
        cached.pop("_key", None)
        self._cache[key] = cached

    def delete(self, key: str) -> bool:
        """Delete a key."""
        self._cache.pop(key, None)
        try:
            return self._storage().scrolls.delete_one("_kv", {"_key": key}).get("deleted", 0) > 0
        except Exception:
            return False

    def query(self, collection: str, filter: dict[str, Any] | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        """Query a scrolls collection."""
        try:
            return self._storage().scrolls.find(collection, filter or {}, limit=limit)
        except Exception:
            return []

    def insert(self, collection: str, doc: dict[str, Any], *, ttl: int | None = None) -> str:
        """Insert a document into a scrolls collection. Returns doc ID."""
        try:
            return self._storage().scrolls.insert(collection, doc, ttl=ttl)
        except Exception:
            return ""

    # ── Files (crates) ──

    def put_file(self, container: str, name: str, data: bytes, *, content_type: str = "", ttl: int | None = None) -> None:
        """Store a binary file."""
        try:
            self._storage().crates.put(container, name, data, content_type=content_type, ttl=ttl)
        except Exception:
            logger.debug("Vault put_file failed: %s/%s/%s", self._owner, container, name)

    def get_file(self, container: str, name: str) -> tuple[bytes, Any] | None:
        """Read a binary file. Returns (data, info) or None."""
        try:
            return self._storage().crates.get(container, name)
        except Exception:
            return None

    def delete_file(self, container: str, name: str) -> bool:
        """Delete a binary file."""
        try:
            return self._storage().crates.delete(container, name)
        except Exception:
            return False

    def list_files(self, container: str, prefix: str = "") -> list[Any]:
        """List files in a container."""
        try:
            return self._storage().crates.list(container, prefix)
        except Exception:
            return []


# ── VaultHandle (other llming — read-only) ──


class VaultHandle:
    """Read-only access to another llming's vault.

        data = self.vaults["system-monitor"].get("state")
        results = self.vaults["system-monitor"].query("history", limit=10)
        data, info = self.vaults["system-monitor"].get_file("exports", "report.pdf")
    """

    def __init__(self, owner: str) -> None:
        self._owner = owner

    def _storage(self) -> Any:
        from hort.storage.store import StorageManager
        return StorageManager.get().get_storage(self._owner).persist

    def get(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            result = self._storage().scrolls.find_one("_kv", {"_key": key})
            if result is None:
                return default if default is not None else {}
            result.pop("_id", None)
            result.pop("_key", None)
            result.pop("_access", None)
            return result
        except Exception:
            return default if default is not None else {}

    def query(self, collection: str, filter: dict[str, Any] | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self._storage().scrolls.find(collection, filter or {}, limit=limit)
        except Exception:
            return []

    def get_file(self, container: str, name: str) -> tuple[bytes, Any] | None:
        try:
            return self._storage().crates.get(container, name)
        except Exception:
            return None

    def list_files(self, container: str, prefix: str = "") -> list[Any]:
        try:
            return self._storage().crates.list(container, prefix)
        except Exception:
            return []


class VaultHandleMap:
    def __init__(self) -> None:
        pass

    def __getitem__(self, owner: str) -> VaultHandle:
        return VaultHandle(owner)


# ── Llming Handle ──


class LlmingHandle:
    """Call another llming's powers.

        result = await self.llmings["system-monitor"].call("get_metrics")
    """

    def __init__(self, target: str, source: str, bus: MessageBus) -> None:
        self._target = target
        self._source = source
        self._bus = bus

    async def call(self, power: str, args: dict[str, Any] | None = None) -> Any:
        return await self._bus.call(
            source=self._source, target=self._target,
            power=power, args=args or {},
        )


class LlmingHandleMap:
    def __init__(self, source: str, bus: MessageBus) -> None:
        self._source = source
        self._bus = bus

    def __getitem__(self, target: str) -> LlmingHandle:
        return LlmingHandle(target, self._source, self._bus)


# ── Channel Handle ──

PulseHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class ChannelHandle:
    """Subscribe to a named pulse channel.

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
    def __init__(self, bus: PulseBus) -> None:
        self._bus = bus

    def __getitem__(self, channel: str) -> ChannelHandle:
        return ChannelHandle(channel, self._bus)
