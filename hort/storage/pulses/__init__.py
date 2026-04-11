"""Pulse extensions — routing into storage + unified scroll/crate pulses.

Extends the existing PulseBus with:
- Route pulses into shelves/holds (auto-insert with timestamp)
- Unified pulses carrying both scrolls and crates
- Peek at latest value without subscribing
- List available pulses (respects access levels)
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class PulseRouter:
    """Routes pulses into storage — auto-insert scrolls/crates with timestamps."""

    def __init__(self) -> None:
        self._routes: dict[str, dict[str, Any]] = {}

    def route(
        self, pulse_name: str,
        into_shelf: Any = None, into_hold: Any = None,
        ttl: int | None = None,
    ) -> None:
        self._routes[pulse_name] = {"shelf": into_shelf, "hold": into_hold, "ttl": ttl}

    def unroute(self, pulse_name: str) -> None:
        self._routes.pop(pulse_name, None)

    def handle(self, pulse_name: str, data: dict[str, Any]) -> None:
        """Route an incoming pulse to storage."""
        route = self._routes.get(pulse_name)
        if not route:
            return

        now = time.time()
        ttl = route.get("ttl")

        scroll_data = data.get("scroll", data) if isinstance(data, dict) else data
        crate_data = data.get("crate") if isinstance(data, dict) else None

        shelf = route.get("shelf")
        if shelf and scroll_data:
            shelf.insert({**scroll_data, "_routed_at": now, "_pulse": pulse_name}, ttl=ttl)

        hold = route.get("hold")
        if hold and crate_data:
            name = crate_data.get("name", f"{pulse_name}_{now:.0f}")
            binary = crate_data.get("data", b"")
            content_type = crate_data.get("content_type", "application/octet-stream")
            if isinstance(binary, bytes):
                hold.put(name, binary, content_type=content_type, ttl=ttl)

    @property
    def routes(self) -> dict[str, dict[str, Any]]:
        return dict(self._routes)


class PulseRegistry:
    """Tracks available pulses for discovery, peek, and subscription."""

    def __init__(self) -> None:
        self._pulses: dict[str, dict[str, dict[str, Any]]] = {}
        self._latest: dict[str, dict[str, Any]] = {}
        self._subscriptions: dict[str, set[str]] = {}

    def register(self, llming: str, name: str, group: str = "public", description: str = "") -> None:
        if llming not in self._pulses:
            self._pulses[llming] = {}
        self._pulses[llming][name] = {"group": group, "description": description}

    def update(self, llming: str, name: str, value: Any) -> None:
        self._latest[f"{llming}/{name}"] = {"value": value, "_ts": time.time()}

    def peek(self, llming: str, name: str) -> dict[str, Any] | None:
        return self._latest.get(f"{llming}/{name}")

    def available(self, viewer_llming: str = "") -> list[dict[str, Any]]:
        result = []
        for llming, pulses in self._pulses.items():
            for name, meta in pulses.items():
                if meta.get("group") == "private" and viewer_llming != llming:
                    continue
                result.append({
                    "llming": llming, "name": name,
                    "group": meta.get("group", "public"),
                    "description": meta.get("description", ""),
                    "subscribed": self.subscribed(viewer_llming, llming, name),
                    "has_value": f"{llming}/{name}" in self._latest,
                })
        return result

    def subscribe(self, subscriber: str, llming: str, name: str) -> None:
        if subscriber not in self._subscriptions:
            self._subscriptions[subscriber] = set()
        self._subscriptions[subscriber].add(f"{llming}/{name}")

    def unsubscribe(self, subscriber: str, llming: str, name: str) -> None:
        if subscriber in self._subscriptions:
            self._subscriptions[subscriber].discard(f"{llming}/{name}")

    def subscribed(self, subscriber: str, llming: str, name: str) -> bool:
        return f"{llming}/{name}" in self._subscriptions.get(subscriber, set())
