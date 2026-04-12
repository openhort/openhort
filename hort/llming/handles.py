"""Vault, llming, and channel handles.

    self.vault.set("state", {"connected": True})
    self.vault.get("state")
    self.vault.put_file("exports", "report.pdf", pdf_bytes)
    data, info = self.vault.get_file("exports", "report.pdf")

    self.vaults["system-monitor"].get("state")

    await self.llmings["hue-bridge"].call("set_light", {...})

    self.channels["cpu_spike"].subscribe(handler)

Reactive vault bindings:

    class Dashboard(Llming):
        cpu = vault_ref('system-monitor', 'state.cpu_percent', default=0)

        @cpu.on_change
        async def on_cpu_spike(self, value, old):
            if value > 90:
                await self.emit('cpu_alert', {'cpu': value})
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from pydantic import BaseModel

if TYPE_CHECKING:
    from hort.llming.bus import MessageBus
    from hort.llming.pulse import PulseBus

logger = logging.getLogger(__name__)


# ── VaultRef (reactive descriptor) ──


class VaultRef:
    """Reactive binding to a vault value.

    Declare as a class attribute. The framework polls the source vault
    and updates the descriptor automatically. Use ``@ref.on_change`` to
    register callbacks that fire when the value changes.

    Example::

        class AlertManager(Llming):
            cpu = vault_ref('system-monitor', 'state.cpu_percent', default=0)
            mem = vault_ref('system-monitor', 'state.mem_percent', default=0)

            @cpu.on_change
            async def on_cpu_spike(self, value, old):
                if value > 90:
                    await self.emit('cpu_alert', {'cpu': value})
    """

    def __init__(self, owner: str, path: str, *, default: Any = None) -> None:
        self.owner = owner
        self.default = default
        self._attr = ""
        self._on_change_handlers: list[Callable] = []

        # Parse path: 'state.cpu_percent' → key='state', props=['cpu_percent']
        dot = path.find(".")
        self.key = path[:dot] if dot >= 0 else path
        self.props = path[dot + 1 :].split(".") if dot >= 0 else []

    def __set_name__(self, owner_cls: type, name: str) -> None:
        self._attr = f"_vr_{name}"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self  # class-level access returns the descriptor
        return getattr(obj, self._attr, self.default)

    def __set__(self, obj: Any, value: Any) -> None:
        old = getattr(obj, self._attr, self.default)
        object.__setattr__(obj, self._attr, value)
        if old != value:
            for handler in self._on_change_handlers:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(handler(obj, value, old))
                except RuntimeError:
                    pass

    def on_change(self, handler: Callable) -> Callable:
        """Decorator: register a callback for value changes."""
        self._on_change_handlers.append(handler)
        return handler

    def _extract(self, data: dict[str, Any]) -> Any:
        """Navigate the property path to extract the bound value."""
        val: Any = data
        for p in self.props:
            if not isinstance(val, dict):
                return self.default
            val = val.get(p, self.default)
        return val if val is not None else self.default

    def poll(self, llming: Any) -> None:
        """Read the vault and update the value. Called by the framework."""
        if self.owner == "self":
            data = llming.vault.get(self.key, {})
        else:
            data = llming.vaults[self.owner].get(self.key, {})
        value = self._extract(data)
        self.__set__(llming, value)


def vault_ref(owner: str, path: str, *, default: Any = None) -> VaultRef:
    """Create a reactive vault binding.

    Args:
        owner: Source llming name, or 'self' for own vault.
        path: Dot-separated path — 'state.cpu_percent'.
        default: Default value when vault is empty.

    Returns:
        VaultRef descriptor for use as a class attribute.
    """
    return VaultRef(owner, path, default=default)


# ── Python vault_ref push registry ──

# {(owner, key): [(llming_instance, VaultRef), ...]}
_python_vault_watchers: dict[tuple[str, str], list[tuple[Any, VaultRef]]] = {}


def register_vault_ref(llming: Any, vr: VaultRef) -> None:
    """Register a VaultRef for push notifications. Called by the framework."""
    resolved_owner = vr.owner if vr.owner != "self" else llming._instance_name
    wk = (resolved_owner, vr.key)
    _python_vault_watchers.setdefault(wk, []).append((llming, vr))
    # Initial read
    vr.poll(llming)


def unregister_vault_refs(llming: Any) -> None:
    """Unregister all VaultRefs for a llming instance. Called on deactivate."""
    for wk in list(_python_vault_watchers):
        _python_vault_watchers[wk] = [
            (inst, vr) for inst, vr in _python_vault_watchers[wk] if inst is not llming
        ]
        if not _python_vault_watchers[wk]:
            del _python_vault_watchers[wk]


def _notify_python_watchers(owner: str, key: str, data: dict[str, Any]) -> None:
    """Called by Vault.set() — update all VaultRef bindings for this key."""
    watchers = _python_vault_watchers.get((owner, key))
    if not watchers:
        return
    for llming, vr in watchers:
        value = vr._extract(data)
        vr.__set__(llming, value)


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
        # Push to watching viewers and Python vault_ref bindings
        try:
            from hort.commands.card_api import notify_vault_change
            notify_vault_change(self._owner, key, cached)
        except Exception:
            pass
        _notify_python_watchers(self._owner, key, cached)

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
