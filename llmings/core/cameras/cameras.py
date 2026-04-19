"""Cameras — security camera feeds with subscriber-aware stream producer."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from hort.llming import Llming

logger = logging.getLogger(__name__)


class Cameras(Llming):
    """Security camera feed viewer.

    Demonstrates the stream producer API:
    - Declares a frame stream channel
    - Reacts to subscriber changes (start/stop capture)
    - Adapts capture parameters to subscriber demands
    - Pushes frames via self.streams[name].emit()

    Real implementation would integrate with actual camera hardware.
    For now, frame data flows via demo.js → vault → useStream in real mode too.
    """

    _capture_task: asyncio.Task | None = None
    _capture_width: int = 160
    _capture_running: bool = False

    def activate(self, config: dict[str, Any] | None = None) -> None:
        # Declare a frame stream per camera. Producers don't have to know
        # which cameras exist upfront — declarations can happen on demand.
        for cam_id in ("frontdoor", "backyard", "garage"):
            handle = self.streams.declare(cam_id)
            handle.on_subscribers_changed(self._make_sub_handler(cam_id))

    def _make_sub_handler(self, cam_id: str):
        async def on_subs_changed(subscribers: list[dict]) -> None:
            if not subscribers:
                logger.info("cameras:%s — no subscribers, stopping capture", cam_id)
                self._capture_running = False
                return
            # Adapt to most demanding subscriber
            max_w = max((s.get("width", 160) for s in subscribers), default=160)
            self._capture_width = max_w
            logger.info(
                "cameras:%s — %d subscriber(s), capture width=%d",
                cam_id, len(subscribers), max_w,
            )
            if not self._capture_running:
                self._capture_running = True
                # In a real implementation this would spawn a per-camera capture loop.
                # For the demo, frames continue to flow via demo.js → vault → useStream.
        return on_subs_changed
