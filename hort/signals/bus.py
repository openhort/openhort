"""In-process signal bus with glob pattern matching and replay buffer."""

from __future__ import annotations

import fnmatch
import logging
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Awaitable, Callable

from hort.signals.models import Signal

logger = logging.getLogger("hort.signals.bus")

SignalCallback = Callable[[Signal], Awaitable[None]]


class _Subscription:
    __slots__ = ("id", "pattern", "callback")

    def __init__(self, id: str, pattern: str, callback: SignalCallback) -> None:
        self.id = id
        self.pattern = pattern
        self.callback = callback


def _matches(pattern: str, signal_type: str) -> bool:
    """Glob match on dot-notation signal types."""
    return fnmatch.fnmatch(signal_type, pattern)


class SignalBus:
    """Pub/sub signal router with pattern matching and replay."""

    def __init__(self, buffer_size: int = 1000) -> None:
        self._subscriptions: dict[str, _Subscription] = {}
        self._buffer: deque[Signal] = deque(maxlen=buffer_size)

    async def emit(self, signal: Signal) -> None:
        """Emit a signal to all matching subscribers.

        Subscriber errors are logged but never propagated.
        """
        self._buffer.append(signal)
        for sub in list(self._subscriptions.values()):
            if _matches(sub.pattern, signal.signal_type):
                try:
                    await sub.callback(signal)
                except Exception:
                    logger.exception("Subscriber %s error", sub.id)

    def subscribe(self, pattern: str, callback: SignalCallback) -> str:
        """Subscribe to signals matching a glob pattern.

        Returns subscription ID for later unsubscribe.
        """
        sub_id = uuid.uuid4().hex[:12]
        self._subscriptions[sub_id] = _Subscription(sub_id, pattern, callback)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""
        self._subscriptions.pop(subscription_id, None)

    async def replay(
        self, pattern: str, since: datetime,
    ) -> list[Signal]:
        """Return recent signals from buffer matching pattern and timestamp."""
        return [
            s for s in self._buffer
            if _matches(pattern, s.signal_type) and s.timestamp >= since
        ]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)


# ── Singleton ───────────────────────────────────────────────────────

_bus: SignalBus | None = None


def get_bus() -> SignalBus:
    """Get or create the global SignalBus."""
    global _bus
    if _bus is None:
        _bus = SignalBus()
    return _bus


def reset_bus() -> None:
    """Reset singleton (for testing)."""
    global _bus
    _bus = None
