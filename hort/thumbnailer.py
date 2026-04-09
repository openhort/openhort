"""Thumbnail rotation scheduler — fixed-bandwidth window thumbnail capture.

Instead of the client requesting all thumbnails simultaneously (which
causes N concurrent Quartz captures), the server maintains a rotation
queue. Thumbnails are captured one at a time at a fixed rate, cycling
through all registered windows.

Bandwidth budget: ~2 captures/second regardless of window count.
- 10 windows → each refreshed every ~5 seconds
- 50 windows → each refreshed every ~25 seconds (capped at 15s by acceleration)

Memory: only 1 CGImage at a time (fixed, not proportional to window count).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger("hort.thumbnailer")

# ── Configuration ───────────────────────────────────────────────────

MIN_INTERVAL = 0.5    # fastest: 2 captures/sec
MAX_CYCLE_TIME = 15.0 # cap: full rotation in at most 15 seconds
THUMB_MAX_WIDTH = 400 # thumbnail resolution (smaller = faster + less memory)
THUMB_QUALITY = 40    # JPEG quality for thumbnails


class ThumbnailScheduler:
    """Rotates through windows, capturing thumbnails one at a time.

    The client subscribes to thumbnail updates via the control WS.
    Instead of requesting individual thumbnails, it receives a stream
    of ``thumbnail`` messages as the scheduler cycles through windows.
    """

    _instance: ThumbnailScheduler | None = None

    def __init__(self) -> None:
        self._window_ids: deque[int] = deque()
        self._target_ids: dict[int, str] = {}  # window_id → target_id
        self._cache: dict[int, str] = {}       # window_id → base64 JPEG
        self._subscribers: set[Any] = set()    # control WS sessions
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @classmethod
    def get(cls) -> ThumbnailScheduler:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        if cls._instance:
            cls._instance.stop()
        cls._instance = None

    def set_windows(self, windows: list[dict[str, Any]]) -> None:
        """Update the window list. Called when the window list refreshes."""
        new_ids = {w["window_id"] for w in windows}
        old_ids = set(self._window_ids)
        # Track which windows are on the current Space (capturable)
        self._on_screen = {w["window_id"] for w in windows if w.get("is_on_screen", True)}

        # Add new windows
        for w in windows:
            wid = w["window_id"]
            if wid not in old_ids:
                self._window_ids.append(wid)
            self._target_ids[wid] = w.get("target_id", "")

        # Remove gone windows
        for wid in old_ids - new_ids:
            try:
                self._window_ids.remove(wid)
            except ValueError:
                pass
            self._target_ids.pop(wid, None)
            self._cache.pop(wid, None)

    def subscribe(self, session: Any) -> None:
        """Register a control WS session to receive thumbnail updates."""
        self._subscribers.add(session)
        if not self._running:
            self.start()

    def unsubscribe(self, session: Any) -> None:
        """Unregister a session."""
        self._subscribers.discard(session)
        if not self._subscribers:
            self.stop()

    def get_cached(self, window_id: int) -> str | None:
        """Get the most recent cached thumbnail (base64 JPEG)."""
        return self._cache.get(window_id)

    def get_all_cached(self) -> dict[int, str]:
        """Get all cached thumbnails."""
        return dict(self._cache)

    def start(self) -> None:
        """Start the rotation loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._rotation_loop())
        logger.info("Thumbnail scheduler started (%d windows)", len(self._window_ids))

    def stop(self) -> None:
        """Stop the rotation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _rotation_loop(self) -> None:
        """Main loop: capture one window per tick, rotate through all."""
        try:
            while self._running:
                if not self._window_ids or not self._subscribers:
                    await asyncio.sleep(1.0)
                    continue

                # Calculate interval: spread captures evenly over the cycle
                n = len(self._window_ids)
                cycle_time = min(n * MIN_INTERVAL, MAX_CYCLE_TIME)
                interval = cycle_time / n
                interval = max(interval, MIN_INTERVAL)

                # Capture the next window in rotation
                window_id = self._window_ids[0]
                self._window_ids.rotate(-1)  # move to back of queue

                # Skip off-screen windows (other Spaces) — capture always returns NULL
                on_screen = getattr(self, "_on_screen", None)
                if on_screen is not None and window_id not in on_screen and window_id >= 0:
                    continue

                target_id = self._target_ids.get(window_id, "")
                jpeg = await self._capture(window_id, target_id)

                if jpeg is not None:
                    b64 = base64.b64encode(jpeg).decode("ascii")
                    self._cache[window_id] = b64
                    del jpeg  # release frame memory immediately

                    # Push to all subscribers
                    msg = {
                        "type": "thumbnail",
                        "window_id": window_id,
                        "data": b64,
                    }
                    dead: list[Any] = []
                    for session in self._subscribers:
                        try:
                            await session.send(msg)
                        except Exception:
                            dead.append(session)
                    for s in dead:
                        self._subscribers.discard(s)

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Thumbnail rotation error")
        finally:
            self._running = False

    @staticmethod
    async def _capture(window_id: int, target_id: str) -> bytes | None:
        """Capture a single window thumbnail in the executor."""
        from hort.targets import TargetRegistry

        registry = TargetRegistry.get()
        provider = (
            registry.get_provider(target_id)
            if target_id
            else registry.get_default()
        )
        if provider is None:
            return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, provider.capture_window,
            window_id, THUMB_MAX_WIDTH, THUMB_QUALITY,
        )
