"""Camera media provider — webcams and virtual cameras.

macOS: AVFoundation for enumeration (zero cost), OpenCV for capture.
Linux/Windows: OpenCV for both.

Cameras are on-demand resources with ref-counted lifecycle:
- ``list_sources()`` enumerates without opening (no resource cost)
- ``start_source()`` opens camera, starts capture thread
- ``stop_source()`` closes camera when last viewer disconnects
- Auto-stops after idle timeout (no viewers for 30s)
"""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
from typing import Any

from hort.media import MediaProvider, MediaSource

logger = logging.getLogger(__name__)

_IDLE_TIMEOUT = 30.0  # seconds before auto-stopping an unused camera


class _CameraSession:
    """Active capture session for a single camera. Ref-counted."""

    def __init__(self, device_index: int, device_name: str) -> None:
        self.device_index = device_index
        self.device_name = device_name
        self.ref_count = 0
        self.last_access = time.monotonic()
        self._capture: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._latest_frame: bytes | None = None
        self._lock = threading.Lock()
        self._width = 0
        self._height = 0
        self._fps = 0.0

    def start(self) -> bool:
        """Open camera and start capture thread."""
        if self._running:
            self.ref_count += 1
            return True

        try:
            import cv2
            cap = cv2.VideoCapture(self.device_index)
            if not cap.isOpened():
                logger.warning("Failed to open camera %d (%s)", self.device_index, self.device_name)
                return False

            self._capture = cap
            self._width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            self._running = True
            self.ref_count = 1
            self.last_access = time.monotonic()

            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            logger.info("Camera started: %s (%dx%d @ %.0ffps)",
                        self.device_name, self._width, self._height, self._fps)
            return True
        except Exception:
            logger.exception("Failed to start camera %s", self.device_name)
            return False

    def stop(self) -> None:
        """Close camera and stop capture thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._capture:
            self._capture.release()
            self._capture = None
        self._latest_frame = None
        self.ref_count = 0
        logger.info("Camera stopped: %s", self.device_name)

    def get_frame(self, max_width: int = 1920, quality: int = 80) -> bytes | None:
        """Get the latest captured frame as WebP bytes."""
        self.last_access = time.monotonic()
        with self._lock:
            return self._latest_frame

    @property
    def info(self) -> dict[str, Any]:
        return {
            "width": self._width,
            "height": self._height,
            "fps": self._fps,
            "active": self._running,
            "ref_count": self.ref_count,
        }

    def _capture_loop(self) -> None:
        """Background thread: continuously read frames from camera."""
        import cv2
        from PIL import Image

        fail_count = 0
        while self._running:
            if self._capture is None:
                break
            ret, frame = self._capture.read()
            if not ret:
                fail_count += 1
                if fail_count > 30:  # ~1 second of failures → camera disconnected
                    logger.warning("Camera disconnected (read failed 30x): %s", self.device_name)
                    self._running = False
                    break
                time.sleep(0.03)
                continue
            fail_count = 0

            # Convert BGR→RGB, encode as WebP
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil = Image.fromarray(rgb)
                buf = io.BytesIO()
                pil.save(buf, format="WEBP", quality=80, method=2)
                pil.close()
                with self._lock:
                    self._latest_frame = buf.getvalue()
                buf.close()
            except Exception:
                pass

            # Cap at ~30fps to avoid spinning
            time.sleep(max(0.001, 1.0 / max(1, self._fps)))


_DISCOVERY_INTERVAL = 5.0  # seconds between background re-enumerations


class CameraProvider(MediaProvider):
    """Webcam media provider. Enumerates cameras, captures on demand.

    Background discovery thread re-enumerates every 5 seconds.
    Cameras that were active and got disconnected are auto-restarted
    when they reappear (matched by unique device ID).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _CameraSession] = {}
        self._device_map: dict[str, int] = {}  # source_id → cv2 device index
        self._cached_sources: list[tuple[int, str, str]] = []  # (idx, name, uid)
        self._wanted: set[str] = set()  # source_ids that should be active
        self._discovery_thread: threading.Thread | None = None
        self._discovery_running = False
        self._start_discovery()

    def _start_discovery(self) -> None:
        """Start background camera discovery thread."""
        if self._discovery_running:
            return
        self._discovery_running = True
        self._discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self._discovery_thread.start()

    def _discovery_loop(self) -> None:
        """Background: re-enumerate cameras, auto-reconnect wanted ones."""
        import asyncio

        while self._discovery_running:
            try:
                new_cameras = _enumerate_cameras()
                old_ids = {f"cam:{uid}" for _, _, uid in self._cached_sources}
                new_ids = {f"cam:{uid}" for _, _, uid in new_cameras}

                # Update cache and device map
                self._cached_sources = new_cameras
                for idx, name, uid in new_cameras:
                    self._device_map[f"cam:{uid}"] = idx

                # Detect newly appeared cameras that are wanted
                appeared = new_ids - old_ids
                for sid in appeared & self._wanted:
                    logger.info("Camera reconnected: %s — auto-restarting", sid)
                    # Find name + index
                    for idx, name, uid in new_cameras:
                        if f"cam:{uid}" == sid:
                            session = _CameraSession(idx, name)
                            if session.start():
                                self._sessions[sid] = session
                            break

                # Detect disappeared cameras — mark sessions as dead
                disappeared = old_ids - new_ids
                for sid in disappeared:
                    session = self._sessions.get(sid)
                    if session and session._running:
                        logger.info("Camera disconnected: %s (%s)", sid, session.device_name)
                        session.stop()
                        # Keep in _wanted so it auto-reconnects

            except Exception:
                pass

            time.sleep(_DISCOVERY_INTERVAL)

    def shutdown(self) -> None:
        """Stop discovery thread and all cameras."""
        self._discovery_running = False
        if self._discovery_thread:
            self._discovery_thread.join(timeout=3.0)
        for session in self._sessions.values():
            if session._running:
                session.stop()
        self._sessions.clear()
        self._wanted.clear()

    def list_sources(self) -> list[MediaSource]:
        """List cameras from the background discovery cache (zero cost)."""
        if not self._cached_sources:
            self._cached_sources = _enumerate_cameras()
            for idx, name, uid in self._cached_sources:
                self._device_map[f"cam:{uid}"] = idx
        sources: list[MediaSource] = []
        for idx, name, uid in self._cached_sources:
            source_id = f"cam:{uid}"
            self._device_map[source_id] = idx
            is_active = source_id in self._sessions and self._sessions[source_id]._running
            sources.append(MediaSource(
                source_id=source_id,
                source_type="camera",
                media_type="video",
                name=name,
                metadata={
                    "device_index": idx,
                    "device_uid": uid,
                    "active": is_active,
                    **(self._sessions[source_id].info if is_active else {}),
                },
                push_mode=True,
            ))
        return sources

    async def start_source(self, source_id: str) -> bool:
        """Open camera. Ref-counted. Tracks as 'wanted' for auto-reconnect."""
        self._wanted.add(source_id)

        if source_id in self._sessions:
            session = self._sessions[source_id]
            if session._running:
                session.ref_count += 1
                return True

        idx = self._device_map.get(source_id)
        if idx is None:
            # Re-enumerate to find the device
            for i, name, uid in _enumerate_cameras():
                sid = f"cam:{uid}"
                self._device_map[sid] = i
                if sid == source_id:
                    idx = i
                    break
        if idx is None:
            return False

        # Get device name
        name = source_id.replace("cam:", "")
        for _, n, uid in self._cached_sources or _enumerate_cameras():
            if f"cam:{uid}" == source_id:
                name = n
                break

        session = _CameraSession(idx, name)
        if session.start():
            self._sessions[source_id] = session
            return True
        return False

    async def stop_source(self, source_id: str) -> None:
        """Close camera when last viewer disconnects. Removes from wanted."""
        self._wanted.discard(source_id)
        session = self._sessions.get(source_id)
        if session is None:
            return
        session.ref_count = max(0, session.ref_count - 1)
        if session.ref_count <= 0:
            session.stop()
            del self._sessions[source_id]

    def is_active(self, source_id: str) -> bool:
        session = self._sessions.get(source_id)
        return session is not None and session._running

    async def capture_frame(
        self, source_id: str, max_width: int = 1920, quality: int = 80,
    ) -> bytes | None:
        """Get latest buffered frame. Auto-starts camera if not active."""
        if not self.is_active(source_id):
            ok = await self.start_source(source_id)
            if not ok:
                return None
            # Wait for first frame
            import asyncio
            for _ in range(30):
                await asyncio.sleep(0.1)
                session = self._sessions.get(source_id)
                if session and session._latest_frame:
                    break

        session = self._sessions.get(source_id)
        if session is None:
            return None
        return session.get_frame(max_width, quality)

    def cleanup_idle(self) -> None:
        """Stop cameras that haven't been accessed recently."""
        now = time.monotonic()
        for source_id in list(self._sessions):
            session = self._sessions[source_id]
            if session._running and session.ref_count <= 0:
                if now - session.last_access > _IDLE_TIMEOUT:
                    logger.info("Auto-stopping idle camera: %s", session.device_name)
                    session.stop()
                    del self._sessions[source_id]


def _enumerate_cameras() -> list[tuple[int, str, str]]:
    """Enumerate cameras: returns [(cv2_index, name, unique_id), ...]

    macOS: uses AVFoundation for names/UIDs (zero cost, no device open).
    Other platforms: probes OpenCV indices 0-4.
    """
    if sys.platform == "darwin":
        return _enumerate_avfoundation()
    return _enumerate_opencv()


def _enumerate_avfoundation() -> list[tuple[int, str, str]]:
    """macOS: enumerate via AVFoundation (no device open needed)."""
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
    """Cross-platform: probe OpenCV indices 0-4."""
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
