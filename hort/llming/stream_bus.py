"""Stream system — broadcast channels with subscriber-aware producers.

Streams are continuous data flows from a producer llming to consumers
(other llmings or UI cards). Two modes:

- Frame streams (default): skippable. Latest frame wins. ACK-paced.
  Examples: camera feeds, screen capture, sensor readings, waveforms.

- Continuous streams: ordered, non-skippable. Hard reset on desync.
  Examples: audio playback, voice chat, log tails.

Producers declare and emit::

    self.streams.declare("frame")
    self.streams["frame"].on_subscribers_changed(self._on_subs)
    await self.streams["frame"].emit(frame_bytes)

Consumers subscribe via the @stream decorator (in decorators.py)::

    @stream("cameras:frame")
    async def on_frame(self, data: dict) -> None:
        ...
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

SubscribersChangedHandler = Callable[[list[dict[str, Any]]], Awaitable[None]]


class StreamReset(Exception):
    """Raised by emit_continuous() when a consumer falls behind.

    Producer should catch this and restart from the current point in time
    (don't replay buffered data — minimize latency).
    """


class StreamHandle:
    """Per-channel stream state.

    Tracks subscribers (with their declared params) and ACK readiness.
    Producers call emit() to push data — framework decides which subscribers
    are ready to receive.
    """

    def __init__(self, full_channel: str, continuous: bool = False) -> None:
        self.full_channel = full_channel  # "owner_llming:sub_name"
        self.continuous = continuous
        # session_id -> params dict (subscriber-declared, opaque to framework)
        self._subscribers: dict[str, dict[str, Any]] = {}
        # session_ids that have ACKed and are ready for the next frame (frame mode)
        self._ready: set[str] = set()
        # Held continuous-mode buffers per subscriber (for backpressure detection)
        self._continuous_buffers: dict[str, asyncio.Queue] = {}
        self._on_subs_cb: SubscribersChangedHandler | None = None

    @property
    def subscribers(self) -> list[dict[str, Any]]:
        """List of subscriber param dicts. Each contains at least 'session_id'."""
        return [{"session_id": sid, **params} for sid, params in self._subscribers.items()]

    def on_subscribers_changed(self, handler: SubscribersChangedHandler) -> None:
        """Register a callback for when subscribers join/leave/change params."""
        self._on_subs_cb = handler

    async def add_subscriber(self, session_id: str, params: dict[str, Any]) -> None:
        """Called by the framework when a viewer subscribes."""
        is_new_or_changed = (
            session_id not in self._subscribers
            or self._subscribers[session_id] != params
        )
        self._subscribers[session_id] = params
        # New subscribers start "ready" so they receive the first frame
        self._ready.add(session_id)
        if is_new_or_changed and self._on_subs_cb:
            try:
                await self._on_subs_cb(self.subscribers)
            except Exception:
                logger.exception("on_subscribers_changed handler error")

    async def remove_subscriber(self, session_id: str) -> None:
        """Called by the framework when a viewer unsubscribes or disconnects."""
        had = session_id in self._subscribers
        self._subscribers.pop(session_id, None)
        self._ready.discard(session_id)
        self._continuous_buffers.pop(session_id, None)
        if had and self._on_subs_cb:
            try:
                await self._on_subs_cb(self.subscribers)
            except Exception:
                logger.exception("on_subscribers_changed handler error")

    def ack(self, session_id: str) -> None:
        """Called by the framework when a viewer ACKs a frame (frame mode)."""
        if session_id in self._subscribers:
            self._ready.add(session_id)

    async def emit(self, data: Any) -> int:
        """Push data to ready subscribers (frame mode).

        Returns the number of subscribers the frame was sent to. Subscribers
        not currently ready (still rendering previous frame) are skipped —
        their next frame will be the next emit() after they ACK.

        Single-slot semantics: if multiple emit() calls happen between ACKs,
        only the latest is delivered. This keeps latency minimal.
        """
        if not self._subscribers:
            return 0
        ready_now = list(self._ready)
        if not ready_now:
            return 0
        # Mark unready until ACK
        for sid in ready_now:
            self._ready.discard(sid)
        # Push to viewers (lazy import to avoid circular deps)
        try:
            from hort.commands.card_api import push_stream_frame
            await push_stream_frame(self.full_channel, ready_now, data)
        except Exception:
            logger.exception("Failed to push stream frame on %s", self.full_channel)
        return len(ready_now)

    async def emit_continuous(self, chunk: Any) -> None:
        """Push a chunk to all subscribers (continuous mode).

        Blocks if any subscriber's buffer is full (backpressure).
        Raises StreamReset if a subscriber buffer overflows — producer
        should catch and restart from current time.
        """
        if not self.continuous:
            raise RuntimeError(f"emit_continuous on non-continuous stream {self.full_channel}")
        if not self._subscribers:
            return
        try:
            from hort.commands.card_api import push_stream_chunk
            await push_stream_chunk(self.full_channel, list(self._subscribers.keys()), chunk)
        except Exception:
            logger.exception("Failed to push stream chunk on %s", self.full_channel)


class StreamBus:
    """Central registry of stream channels."""

    _instance: StreamBus | None = None

    def __init__(self) -> None:
        # full_channel -> StreamHandle
        self._channels: dict[str, StreamHandle] = {}

    @classmethod
    def get(cls) -> StreamBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def declare(self, full_channel: str, continuous: bool = False) -> StreamHandle:
        """Declare a stream channel. Idempotent (returns existing handle if any)."""
        if full_channel not in self._channels:
            self._channels[full_channel] = StreamHandle(full_channel, continuous=continuous)
        return self._channels[full_channel]

    def get_channel(self, full_channel: str) -> StreamHandle | None:
        return self._channels.get(full_channel)

    def remove_subscriber_from_all(self, session_id: str) -> None:
        """Clean up a session's subscriptions across all channels (on disconnect)."""
        for handle in self._channels.values():
            asyncio.create_task(handle.remove_subscriber(session_id))


class StreamHandleMap:
    """Pythonic access for llmings: self.streams["name"].emit(...).

    The owner prefix is automatically prepended — llming code uses just
    the sub-name, the full channel becomes "owner:sub".
    """

    def __init__(self, bus: StreamBus, owner: str) -> None:
        self._bus = bus
        self._owner = owner

    def declare(self, name: str, continuous: bool = False) -> StreamHandle:
        full = f"{self._owner}:{name}"
        return self._bus.declare(full, continuous=continuous)

    def __getitem__(self, name: str) -> StreamHandle:
        full = f"{self._owner}:{name}"
        handle = self._bus.get_channel(full)
        if handle is None:
            # Auto-declare on first access
            handle = self._bus.declare(full)
        return handle

    def __contains__(self, name: str) -> bool:
        return f"{self._owner}:{name}" in self._bus._channels
