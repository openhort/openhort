"""Browser camera session — receives frames from a browser via WebSocket.

A browser camera is just another camera session in the CameraProvider.
The difference from native cameras: frames arrive over WS from the browser
instead of being captured locally via OpenCV.

The browser sends:
1. ``camera_offer`` via control WS — registers the camera, sends metadata
2. Binary frames via stream WS (same FRAME_HEADER as screen streaming)
3. ``camera_stop`` via control WS — unregisters

The server:
1. Creates a ``BrowserCameraSession`` (same interface as ``_CameraSession``)
2. Buffers the latest frame (single-slot, drop old)
3. Exposes it as a ``MediaSource`` via the CameraProvider
4. ACK flow: server sends ``camera_ack`` after consuming a frame
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class BrowserCameraSession:
    """A camera session backed by browser frames (not OpenCV).

    Same interface as _CameraSession in media_camera.py so CameraProvider
    can manage both uniformly.
    """

    def __init__(self, session_id: str, device_name: str, width: int, height: int) -> None:
        self.device_index = -1  # no physical device
        self.device_name = device_name
        self.ref_count = 1
        self.last_access = time.monotonic()
        self._running = True
        self._latest_frame: bytes | None = None
        self._lock = threading.Lock()
        self._width = width
        self._height = height
        self._fps = 0.0
        self._frame_count = 0
        self._fps_start = time.monotonic()
        self._session_id = session_id  # WS session that owns this camera

    def receive_frame(self, frame_bytes: bytes) -> None:
        """Called by the WS handler when a frame arrives from the browser."""
        with self._lock:
            self._latest_frame = frame_bytes
        self.last_access = time.monotonic()
        self._frame_count += 1
        elapsed = time.monotonic() - self._fps_start
        if elapsed > 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_start = time.monotonic()

    def get_frame(self, max_width: int = 1920, quality: int = 80) -> bytes | None:
        self.last_access = time.monotonic()
        with self._lock:
            return self._latest_frame

    def start(self) -> bool:
        self._running = True
        logger.info("Browser camera started: %s (%dx%d)", self.device_name, self._width, self._height)
        return True

    def stop(self) -> None:
        self._running = False
        self._latest_frame = None
        logger.info("Browser camera stopped: %s", self.device_name)

    @property
    def info(self) -> dict[str, Any]:
        return {
            "width": self._width,
            "height": self._height,
            "fps": round(self._fps, 1),
            "active": self._running,
            "ref_count": self.ref_count,
            "browser": True,
            "session_id": self._session_id,
        }
