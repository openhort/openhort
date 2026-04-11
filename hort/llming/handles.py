"""Dict-like accessors for cross-llming communication.

Provides Pythonic access patterns::

    await self.llmings["system-monitor"].call("get_metrics")
    await self.vaults["system-monitor"].read("latest_metrics")
    self.channels["cpu_spike"].subscribe(self.on_spike)

Each handle is injected by the framework at activation time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from hort.llming.bus import MessageBus
    from hort.llming.pulse import PulseBus

logger = logging.getLogger(__name__)


# ── Llming Handle ──


class LlmingHandle:
    """Proxy for calling another llming's powers.

    Usage::

        result = await self.llmings["system-monitor"].call("get_metrics")
        result = await self.llmings["llming-cam"].call("enable_camera", {"name": "insta360"})
    """

    def __init__(self, target: str, source: str, bus: MessageBus) -> None:
        self._target = target
        self._source = source
        self._bus = bus

    async def call(self, power: str, args: dict[str, Any] | None = None) -> Any:
        """Call a power on this llming."""
        return await self._bus.call(
            source=self._source,
            target=self._target,
            power=power,
            args=args or {},
        )


class LlmingHandleMap:
    """Dict-like access to other llmings: ``self.llmings["name"]``.

    Returns a LlmingHandle for calling powers on the target.
    """

    def __init__(self, source: str, bus: MessageBus) -> None:
        self._source = source
        self._bus = bus

    def __getitem__(self, target: str) -> LlmingHandle:
        return LlmingHandle(target, self._source, self._bus)


# ── Vault Handle ──


class VaultHandle:
    """Read access to another llming's vault.

    Usage::

        data = await self.vaults["system-monitor"].read("latest_metrics")
        entries = await self.vaults["system-monitor"].query("history", {"cpu": {"$gt": 90}})
    """

    def __init__(self, owner: str, reader: str) -> None:
        self._owner = owner
        self._reader = reader

    async def read(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read a key from the owner's vault."""
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
            logger.debug("Vault read failed: %s/%s", self._owner, key)
            return default if default is not None else {}

    async def query(
        self, collection: str, filter: dict[str, Any] | None = None, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Query a collection in the owner's vault."""
        from hort.storage.store import StorageManager
        try:
            storage = StorageManager.get().get_storage(self._owner)
            return storage.persist.scrolls.find(collection, filter or {}, limit=limit)
        except Exception:
            logger.debug("Vault query failed: %s/%s", self._owner, collection)
            return []


class VaultHandleMap:
    """Dict-like access to other llmings' vaults: ``self.vaults["name"]``."""

    def __init__(self, reader: str) -> None:
        self._reader = reader

    def __getitem__(self, owner: str) -> VaultHandle:
        return VaultHandle(owner, self._reader)


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
        """Subscribe to events on this channel."""
        self._bus.subscribe_channel(self._channel, handler)

    def unsubscribe(self, handler: PulseHandler) -> None:
        """Unsubscribe from this channel."""
        self._bus.unsubscribe_channel(self._channel, handler)


class ChannelHandleMap:
    """Dict-like access to pulse channels: ``self.channels["name"]``."""

    def __init__(self, bus: PulseBus) -> None:
        self._bus = bus

    def __getitem__(self, channel: str) -> ChannelHandle:
        return ChannelHandle(channel, self._bus)
