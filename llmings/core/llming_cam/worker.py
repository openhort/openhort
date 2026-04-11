"""Camera discovery worker — thin subprocess.

Does transport only:
- Enumerates cameras via AVFoundation/OpenCV
- Reports camera additions/removals to main via IPC
- Main handles policies, sessions, streaming

Runs the discovery loop that was previously a thread inside CameraProvider.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

from hort.lifecycle.worker import Worker

logger = logging.getLogger(__name__)

_DISCOVERY_INTERVAL = 5.0


class CameraWorker(Worker):
    name = "camera"
    protocol_version = 1

    def __init__(self) -> None:
        super().__init__()
        self._discovery_task: asyncio.Task | None = None
        self._last_cameras: list[tuple[int, str, str]] = []

    async def on_connected(self) -> None:
        """Start camera discovery loop."""
        if self._discovery_task and not self._discovery_task.done():
            return
        self._discovery_task = asyncio.create_task(self._discovery_loop())

    async def on_message(self, msg: dict) -> None:
        """Handle messages from main."""
        if msg.get("type") == "enumerate":
            # On-demand enumeration request
            cameras = await asyncio.get_event_loop().run_in_executor(None, _enumerate_cameras)
            await self.send({"type": "cameras", "cameras": [
                {"index": idx, "name": name, "uid": uid} for idx, name, uid in cameras
            ]})

    async def on_disconnected(self) -> None:
        """Main disconnected — keep discovering."""
        logger.info("Main disconnected, continuing discovery")

    async def _discovery_loop(self) -> None:
        """Background: enumerate cameras every 5 seconds, report changes."""
        while self._running:
            try:
                cameras = await asyncio.get_event_loop().run_in_executor(None, _enumerate_cameras)
                new_set = {(idx, name, uid) for idx, name, uid in cameras}
                old_set = {(idx, name, uid) for idx, name, uid in self._last_cameras}

                if new_set != old_set:
                    appeared = new_set - old_set
                    disappeared = old_set - new_set

                    await self.send({"type": "cameras_changed", "cameras": [
                        {"index": idx, "name": name, "uid": uid} for idx, name, uid in cameras
                    ], "appeared": [
                        {"index": idx, "name": name, "uid": uid} for idx, name, uid in appeared
                    ], "disappeared": [
                        {"index": idx, "name": name, "uid": uid} for idx, name, uid in disappeared
                    ]})

                    self._last_cameras = cameras
                elif not self._last_cameras:
                    # First run — send initial list
                    self._last_cameras = cameras
                    await self.send({"type": "cameras", "cameras": [
                        {"index": idx, "name": name, "uid": uid} for idx, name, uid in cameras
                    ]})
            except Exception:
                pass

            await asyncio.sleep(_DISCOVERY_INTERVAL)


def _enumerate_cameras() -> list[tuple[int, str, str]]:
    """Enumerate cameras — same logic as media_camera.py."""
    if sys.platform == "darwin":
        return _enumerate_avfoundation()
    return _enumerate_opencv()


def _enumerate_avfoundation() -> list[tuple[int, str, str]]:
    try:
        import AVFoundation
        devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(
            AVFoundation.AVMediaTypeVideo
        )
        result = []
        for i, d in enumerate(devices):
            result.append((i, str(d.localizedName()), str(d.uniqueID())))
        return result
    except ImportError:
        return _enumerate_opencv()


def _enumerate_opencv() -> list[tuple[int, str, str]]:
    try:
        import cv2
    except ImportError:
        return []
    result = []
    for i in range(5):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            result.append((i, f"Camera {i}", str(i)))
            cap.release()
    return result


if __name__ == "__main__":
    CameraWorker().run()
