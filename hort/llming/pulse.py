"""Pulse system — live state and subscribable events.

Every llming can:
- Expose live state via ``get_pulse()`` (static read)
- Emit events via ``emit_pulse()`` (push to subscribers)
- Declare subscribable channels via ``get_pulse_channels()``

Other llmings subscribe via the message bus — no direct imports.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

PulseHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class PulseBus:
    """Central event bus for llming pulse events.

    Routes events from emitters to subscribers. Enforces isolation —
    llmings never reference each other directly, only by instance name.
    """

    _instance: PulseBus | None = None

    def __init__(self) -> None:
        # {source_instance: {event_name: [handler, ...]}}
        self._subscriptions: dict[str, dict[str, list[PulseHandler]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # {instance_name: latest_pulse_state}
        self._pulse_state: dict[str, dict[str, Any]] = {}

    @classmethod
    def get(cls) -> PulseBus:
        """Get or create the singleton PulseBus."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def subscribe(
        self,
        source: str,
        event: str,
        handler: PulseHandler,
    ) -> None:
        """Subscribe to pulse events from a specific llming."""
        self._subscriptions[source][event].append(handler)

    def unsubscribe(self, source: str, event: str, handler: PulseHandler | None = None) -> None:
        """Unsubscribe from pulse events.

        If handler is None, removes all handlers for this source+event.
        """
        if source not in self._subscriptions:
            return
        if event not in self._subscriptions[source]:
            return
        if handler is None:
            del self._subscriptions[source][event]
        else:
            handlers = self._subscriptions[source][event]
            self._subscriptions[source][event] = [h for h in handlers if h is not handler]

    async def emit(self, source: str, event: str, data: dict[str, Any]) -> None:
        """Emit a pulse event. Delivers to all subscribers asynchronously."""
        handlers = self._subscriptions.get(source, {}).get(event, [])
        for handler in handlers:
            try:
                await handler(data)
            except Exception:
                logger.exception(
                    "Pulse handler error: %s/%s", source, event
                )

    def update_state(self, instance: str, state: dict[str, Any]) -> None:
        """Update the cached pulse state for an instance."""
        self._pulse_state[instance] = state

    def read_state(self, instance: str) -> dict[str, Any]:
        """Read the cached pulse state for an instance."""
        return self._pulse_state.get(instance, {})

    def clear_instance(self, instance: str) -> None:
        """Remove all subscriptions and state for an instance (on deactivate)."""
        self._subscriptions.pop(instance, None)
        self._pulse_state.pop(instance, None)
        # Also remove any subscriptions TO this instance from others
        for source_subs in self._subscriptions.values():
            for event_handlers in source_subs.values():
                # Can't easily identify which handlers belong to which instance
                # without a reverse mapping — left for the instance's deactivate()
                pass
