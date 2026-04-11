"""Pulse system — named channel pub/sub.

Pulses are fire-and-forget events on named channels. Multiple llmings
can publish to the same channel. Subscribers listen by channel name,
not by source llming.

Publishing::

    await self.emit("cpu_spike", CpuSpike(cpu=95, threshold=90))

Subscribing::

    self.channels["cpu_spike"].subscribe(self.on_spike)

``get_pulse()`` still exists for UI thumbnail rendering — it is NOT
part of the cross-llming pulse channel system.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

PulseHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class PulseBus:
    """Central event bus for named pulse channels.

    Channels are global names (not scoped to a llming instance).
    Any llming can publish to any channel. Subscribers receive
    all events on channels they subscribe to.
    """

    _instance: PulseBus | None = None

    def __init__(self) -> None:
        # Named channels: {channel_name: [handler, ...]}
        self._channels: dict[str, list[PulseHandler]] = defaultdict(list)
        # Legacy: instance-scoped subscriptions (backward compat)
        self._subscriptions: dict[str, dict[str, list[PulseHandler]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # UI pulse state cache (for get_pulse / thumbnails only)
        self._pulse_state: dict[str, dict[str, Any]] = {}

    @classmethod
    def get(cls) -> PulseBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ── Named channels (new) ──

    def subscribe_channel(self, channel: str, handler: PulseHandler) -> None:
        """Subscribe to a named channel."""
        if handler not in self._channels[channel]:
            self._channels[channel].append(handler)

    def unsubscribe_channel(self, channel: str, handler: PulseHandler) -> None:
        """Unsubscribe from a named channel."""
        handlers = self._channels.get(channel, [])
        self._channels[channel] = [h for h in handlers if h is not handler]

    async def emit_channel(self, channel: str, data: dict[str, Any]) -> None:
        """Emit an event on a named channel + push to subscribed viewers."""
        # Python handlers
        for handler in self._channels.get(channel, []):
            try:
                await handler(data)
            except Exception:
                logger.exception("Channel handler error: %s", channel)

        # Push to viewers (JS cards) subscribed via card.subscribe
        await self._push_to_viewers(channel, data)

    async def _push_to_viewers(self, channel: str, data: dict[str, Any]) -> None:
        """Push pulse event to all viewer WebSockets subscribed to this channel."""
        try:
            from hort.commands.card_api import get_viewer_subscriptions
            from hort.session import HortRegistry

            subs = get_viewer_subscriptions()
            if not subs:
                return

            registry = HortRegistry.get()
            msg = {"type": "pulse", "channel": channel, "data": data}

            for sid, channels in subs.items():
                if channel not in channels:
                    continue
                try:
                    entry = registry.get_session(sid)
                    if entry and hasattr(entry, "controller") and entry.controller:
                        await entry.controller.send(msg)
                except Exception:
                    pass
        except Exception:
            pass  # Registry not ready during startup

    # ── Legacy instance-scoped (backward compat) ──

    def subscribe(self, source: str, event: str, handler: PulseHandler) -> None:
        self._subscriptions[source][event].append(handler)

    def unsubscribe(self, source: str, event: str, handler: PulseHandler | None = None) -> None:
        if source not in self._subscriptions or event not in self._subscriptions[source]:
            return
        if handler is None:
            del self._subscriptions[source][event]
        else:
            handlers = self._subscriptions[source][event]
            self._subscriptions[source][event] = [h for h in handlers if h is not handler]

    async def emit(self, source: str, event: str, data: dict[str, Any]) -> None:
        """Emit — delivers to both named channel AND legacy instance-scoped subscribers."""
        # Named channel
        await self.emit_channel(event, data)
        # Legacy instance-scoped
        for handler in self._subscriptions.get(source, {}).get(event, []):
            try:
                await handler(data)
            except Exception:
                logger.exception("Pulse handler error: %s/%s", source, event)

    # ── UI pulse state (for thumbnails only) ──

    def update_state(self, instance: str, state: dict[str, Any]) -> None:
        self._pulse_state[instance] = state

    def read_state(self, instance: str) -> dict[str, Any]:
        return self._pulse_state.get(instance, {})

    def clear_instance(self, instance: str) -> None:
        self._subscriptions.pop(instance, None)
        self._pulse_state.pop(instance, None)
