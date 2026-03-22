"""Openhort session entry and registry (built on llming-com)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from llming_com import BaseSessionEntry, BaseSessionRegistry

from hort.models import StreamConfig


@dataclass
class HortSessionEntry(BaseSessionEntry):
    """Session state for one connected viewer client.

    ``websocket`` (inherited) holds the **control** WebSocket (JSON).
    ``stream_ws`` holds the **binary stream** WebSocket (JPEG frames).
    """

    stream_config: Optional[StreamConfig] = None
    stream_ws: Optional[Any] = None  # binary WebSocket
    active_window_id: int = 0
    active_target_id: str = ""  # which target owns the active window
    observer_id: int = 0


class HortRegistry(BaseSessionRegistry["HortSessionEntry"]):
    """Singleton session registry for openhort."""

    _observer_counter: int = 0

    def next_observer_id(self) -> int:
        """Allocate a unique observer ID."""
        self._observer_counter += 1
        return self._observer_counter

    def observer_count(self) -> int:
        """Return the number of sessions with an active stream."""
        return sum(
            1
            for entry in self._sessions.values()
            if entry.stream_ws is not None
        )

    @classmethod
    def reset(cls) -> None:
        """Reset singleton and observer counter (for testing)."""
        super().reset()
        cls._observer_counter = 0
