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

_IDLE_TIMEOUT = 30.0    # seconds before auto-stopping an unused "on" camera
_AUTO_TIMEOUT = 10.0    # seconds before auto-stopping an "auto" transient camera


class _CameraSession:
    """Active capture session for a single camera. Ref-counted.

    Tries OpenCV first. If OpenCV opens but can't read frames (common
    with USB cameras on macOS), falls back to native AVFoundation capture.
    """

    def __init__(self, device_index: int, device_name: str, device_uid: str = "") -> None:
        self.device_index = device_index
        self.device_name = device_name
        self.device_uid = device_uid
        self.ref_count = 0
        self.last_access = time.monotonic()
        self._capture: Any = None       # cv2.VideoCapture or None
        self._avf_session: Any = None   # AVCaptureSession (fallback)
        self._avf_delegate: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._latest_frame: bytes | None = None
        self._lock = threading.Lock()
        self._width = 0
        self._height = 0
        self._fps = 0.0
        self._backend = ""  # "opencv" or "avfoundation"

    def start(self) -> bool:
        """Open camera and start capture thread."""
        if self._running:
            self.ref_count += 1
            return True

        # Try OpenCV first
        if self._start_opencv():
            return True

        # Fallback: native AVFoundation (macOS only)
        if sys.platform == "darwin" and self.device_uid:
            if self._start_avfoundation():
                return True

        logger.warning("Failed to start camera %s (both OpenCV and AVFoundation)", self.device_name)
        return False

    def _start_opencv(self) -> bool:
        try:
            import cv2
            cap = cv2.VideoCapture(self.device_index)
            if not cap.isOpened():
                return False

            # Verify camera can actually produce frames (2s timeout)
            for _ in range(60):
                ret, _ = cap.read()
                if ret:
                    break
                time.sleep(0.033)
            else:
                logger.info("Camera %s: OpenCV can't read frames, trying AVFoundation", self.device_name)
                cap.release()
                return False

            self._capture = cap
            self._width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            self._running = True
            self._backend = "opencv"
            self.ref_count = 1
            self.last_access = time.monotonic()
            self._thread = threading.Thread(target=self._capture_loop_opencv, daemon=True)
            self._thread.start()
            logger.info("Camera started (OpenCV): %s (%dx%d @ %.0ffps)",
                        self.device_name, self._width, self._height, self._fps)
            return True
        except Exception:
            return False

    def _start_avfoundation(self) -> bool:
        """Start capture via native AVFoundation (macOS). Works with USB cameras
        that OpenCV can't handle.

        The delegate runs on a dispatch queue and pushes frames directly
        into self._latest_frame — no capture thread needed.
        """
        self._running = True
        self._backend = "avfoundation"
        self.ref_count = 1
        self.last_access = time.monotonic()
        self._fps = 30.0
        self._width = 1920
        self._height = 1080
        self._frame_count = 0
        self._fps_start = time.monotonic()

        ok = _avf_start_capture(self.device_uid, self)
        if not ok:
            self._running = False
            return False
        logger.info("Camera started (AVFoundation): %s", self.device_name)
        return True

    def stop(self) -> None:
        """Close camera and stop capture thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._capture:
            self._capture.release()
            self._capture = None
        if self._avf_session:
            self._avf_session.stopRunning()
            self._avf_session = None
            self._avf_delegate = None
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
            "backend": self._backend,
        }

    def _capture_loop_opencv(self) -> None:
        """Background thread: continuously read frames from camera (OpenCV)."""
        import cv2
        from PIL import Image

        fail_count = 0
        while self._running:
            if self._capture is None:
                break
            ret, frame = self._capture.read()
            if not ret:
                fail_count += 1
                if fail_count > 150:
                    logger.warning("Camera disconnected (read failed 150x): %s", self.device_name)
                    self._running = False
                    break
                time.sleep(0.03)
                continue
            fail_count = 0

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

            time.sleep(max(0.001, 1.0 / max(1, self._fps)))


_DISCOVERY_INTERVAL = 5.0  # seconds between background re-enumerations

# Camera access policy per device
# "off"  — disabled, nobody can use it (default for privacy)
# "on"   — actively running, AI and viewers can use freely
# "auto" — idle but AI can open transiently for one-shot captures
CAMERA_POLICY_OFF = "off"
CAMERA_POLICY_ON = "on"
CAMERA_POLICY_AUTO = "auto"


class CameraProvider(MediaProvider):
    """Webcam media provider. Enumerates cameras, captures on demand.

    Background discovery thread re-enumerates every 5 seconds.
    Cameras that were active and got disconnected are auto-restarted
    when they reappear (matched by unique device ID).
    """

    def __init__(self, use_subprocess: bool = False) -> None:
        self._sessions: dict[str, _CameraSession] = {}
        self._device_map: dict[str, int] = {}  # source_id → cv2 device index
        self._cached_sources: list[tuple[int, str, str]] = []  # (idx, name, uid)
        self._wanted: set[str] = set()  # source_ids that should be active
        self._policies: dict[str, str] = {}  # source_id → "off"/"on"/"auto"
        self._browser_devices: dict[str, str] = {}  # source_id → device label (idle browser cams)
        self._discovery_thread: threading.Thread | None = None
        self._discovery_running = False
        self._managed: Any = None  # ManagedProcess for discovery subprocess
        if use_subprocess:
            self._start_discovery_subprocess()
        else:
            self._start_discovery()

    def register_browser_device(self, source_id: str, label: str) -> None:
        """Register a browser camera device as available (not streaming yet)."""
        self._browser_devices[source_id] = label

    def _start_discovery(self) -> None:
        """Start background camera discovery thread (legacy, in-process)."""
        if self._discovery_running:
            return
        self._discovery_running = True
        self._discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self._discovery_thread.start()

    def _start_discovery_subprocess(self) -> None:
        """Start camera discovery as a managed subprocess."""
        import asyncio
        from hort.lifecycle import ManagedProcess

        provider = self

        class _CameraDiscovery(ManagedProcess):
            name = "camera"
            protocol_version = 1

            def build_command(self) -> list[str]:
                import sys
                return [sys.executable, "-m", "hort.extensions.core.llming_cam.worker"]

            async def on_message(self, msg: dict) -> None:
                msg_type = msg.get("type", "")
                if msg_type in ("cameras", "cameras_changed"):
                    cameras = msg.get("cameras", [])
                    provider._cached_sources = [
                        (c["index"], c["name"], c["uid"]) for c in cameras
                    ]
                    for idx, name, uid in provider._cached_sources:
                        provider._device_map[f"cam:{uid}"] = idx

                    # Auto-reconnect wanted cameras
                    new_ids = {f"cam:{uid}" for _, _, uid in provider._cached_sources}
                    for sid in list(provider._wanted):
                        if sid in new_ids and sid not in provider._sessions:
                            for idx, name, uid in provider._cached_sources:
                                if f"cam:{uid}" == sid:
                                    session = _CameraSession(idx, name, uid)
                                    if session.start():
                                        provider._sessions[sid] = session
                                    break

                    # Cleanup idle
                    provider.cleanup_idle()

        self._managed = _CameraDiscovery()

        async def _start() -> None:
            await self._managed.start()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_start())
            else:
                loop.run_until_complete(_start())
        except Exception:
            # Fallback to thread
            logger.warning("Failed to start camera subprocess, falling back to thread")
            self._start_discovery()

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
                            session = _CameraSession(idx, name, uid)
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

            # Auto-reconnect wanted cameras that dropped
            try:
                for sid in list(self._wanted):
                    if sid in new_ids and sid not in self._sessions:
                        for idx, name, uid in new_cameras:
                            if f"cam:{uid}" == sid:
                                logger.info("Auto-reconnecting wanted camera: %s", name)
                                session = _CameraSession(idx, name, uid)
                                if session.start():
                                    self._sessions[sid] = session
                                break
                    elif sid in self._sessions and not self._sessions[sid]._running:
                        # Session exists but stopped — restart
                        old = self._sessions.pop(sid)
                        for idx, name, uid in new_cameras:
                            if f"cam:{uid}" == sid:
                                logger.info("Restarting dropped camera: %s", name)
                                session = _CameraSession(idx, name, uid)
                                if session.start():
                                    self._sessions[sid] = session
                                break
            except Exception:
                pass

            # Clean up idle/transient cameras
            try:
                self.cleanup_idle()
            except Exception:
                pass

            time.sleep(_DISCOVERY_INTERVAL)

    def shutdown(self) -> None:
        """Stop discovery (thread or subprocess) and all cameras."""
        self._discovery_running = False
        if self._discovery_thread:
            self._discovery_thread.join(timeout=3.0)
        if self._managed:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._managed.stop())
                else:
                    loop.run_until_complete(self._managed.stop())
            except Exception:
                pass
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
                    "policy": self.get_policy(source_id),
                    **(self._sessions[source_id].info if is_active else {}),
                },
                push_mode=True,
            ))

        # Include browser camera sessions (not in _cached_sources)
        native_ids = {f"cam:{uid}" for _, _, uid in self._cached_sources}
        for source_id, session in self._sessions.items():
            if source_id not in native_ids:
                sources.append(MediaSource(
                    source_id=source_id,
                    source_type="camera",
                    media_type="video",
                    name=session.device_name,
                    metadata={
                        "active": session._running,
                        "policy": self.get_policy(source_id),
                        **session.info,
                    },
                    push_mode=True,
                ))

        # Include registered browser devices that don't have active sessions
        for source_id, name in self._browser_devices.items():
            if source_id not in native_ids and source_id not in self._sessions:
                sources.append(MediaSource(
                    source_id=source_id,
                    source_type="camera",
                    media_type="video",
                    name=name,
                    metadata={
                        "active": False,
                        "policy": self.get_policy(source_id),
                        "browser": True,
                        "width": 0, "height": 0, "fps": 0,
                        "ref_count": 0,
                    },
                    push_mode=True,
                ))

        return sources

    def get_policy(self, source_id: str) -> str:
        """Get the access policy for a camera.

        Default: off. But if the camera is actively running (in _wanted),
        it's implicitly "on" even if no policy was explicitly set.
        """
        explicit = self._policies.get(source_id)
        if explicit:
            return explicit
        if source_id in self._wanted:
            return CAMERA_POLICY_ON
        return CAMERA_POLICY_OFF

    def set_policy(self, source_id: str, policy: str) -> None:
        """Set access policy: 'off', 'on', or 'auto'."""
        self._policies[source_id] = policy

    async def start_source(self, source_id: str) -> bool:
        """Open camera. Ref-counted. Tracks as 'wanted' for auto-reconnect.

        Requires policy 'on' or 'auto'. Fails silently if 'off'.
        Sets policy to 'on' (user explicitly started).
        """
        policy = self.get_policy(source_id)
        if policy == CAMERA_POLICY_OFF:
            # User starting a camera implies enabling it
            self.set_policy(source_id, CAMERA_POLICY_ON)
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

        # Get device name and UID
        dev_uid = source_id.replace("cam:", "")
        name = dev_uid
        for _, n, uid in self._cached_sources or _enumerate_cameras():
            if f"cam:{uid}" == source_id:
                name = n
                dev_uid = uid
                break

        session = _CameraSession(idx, name, dev_uid)
        if session.start():
            self._sessions[source_id] = session
            return True
        return False

    async def stop_source(self, source_id: str) -> None:
        """Close camera when last viewer disconnects. Keeps policy as 'auto'."""
        self._wanted.discard(source_id)
        # Don't set to "off" — stopping keeps auto mode so AI can still one-shot
        if self.get_policy(source_id) == CAMERA_POLICY_ON:
            self.set_policy(source_id, CAMERA_POLICY_AUTO)
        session = self._sessions.get(source_id)
        if session is None:
            return
        session.ref_count = max(0, session.ref_count - 1)
        if session.ref_count <= 0:
            session.stop()
            del self._sessions[source_id]

    async def _start_transient(self, source_id: str) -> bool:
        """Open camera temporarily (for one-shot capture). Does NOT add to _wanted."""
        idx = self._device_map.get(source_id)
        if idx is None:
            for i, name, uid in self._cached_sources or _enumerate_cameras():
                sid = f"cam:{uid}"
                self._device_map[sid] = i
                if sid == source_id:
                    idx = i
                    break
        if idx is None:
            return False

        dev_uid = source_id.replace("cam:", "")
        name = dev_uid
        for _, n, uid in self._cached_sources or _enumerate_cameras():
            if f"cam:{uid}" == source_id:
                name = n
                dev_uid = uid
                break

        session = _CameraSession(idx, name, dev_uid)
        if session.start():
            self._sessions[source_id] = session
            return True
        return False

    def is_active(self, source_id: str) -> bool:
        session = self._sessions.get(source_id)
        return session is not None and session._running

    async def capture_frame(
        self, source_id: str, max_width: int = 1920, quality: int = 80,
    ) -> bytes | None:
        """Get latest buffered frame.

        If camera not active, does a transient open (captures one frame,
        then stops). Does NOT add to _wanted — use start_source() for
        persistent activation.
        """
        # Enforce policy
        policy = self.get_policy(source_id)
        if policy == CAMERA_POLICY_OFF:
            return None  # camera disabled by user

        transient = False
        if not self.is_active(source_id):
            if policy != CAMERA_POLICY_AUTO and policy != CAMERA_POLICY_ON:
                return None
            # Transient capture — open, grab frame, close
            ok = await self._start_transient(source_id)
            if not ok:
                return None
            transient = True
            import asyncio
            for _ in range(30):
                await asyncio.sleep(0.1)
                session = self._sessions.get(source_id)
                if session and session._latest_frame:
                    break

        session = self._sessions.get(source_id)
        if session is None:
            return None

        # Wait for first frame if camera just started (up to 3s)
        if session._latest_frame is None and session._running:
            import asyncio
            for _ in range(30):
                await asyncio.sleep(0.1)
                if session._latest_frame is not None:
                    break

        frame = session.get_frame(max_width, quality)

        # Transient (auto-mode) capture: schedule auto-stop after 10 seconds
        # Camera stays open briefly in case AI makes follow-up captures
        if transient and source_id not in self._wanted:
            session.last_access = time.monotonic()
            # Don't stop immediately — cleanup_idle handles it after _AUTO_TIMEOUT

        return frame

    def cleanup_idle(self) -> None:
        """Stop cameras that haven't been accessed recently.

        - "on" cameras with ref_count=0: stop after _IDLE_TIMEOUT (30s)
        - "auto" transient cameras: stop after _AUTO_TIMEOUT (10s)
        """
        now = time.monotonic()
        for source_id in list(self._sessions):
            session = self._sessions[source_id]
            if not session._running:
                continue
            # Browser cameras are managed by their WS connection, not idle timer
            if session.device_index == -1:
                continue
            policy = self.get_policy(source_id)
            # "auto" transient cameras: short timeout
            if policy == CAMERA_POLICY_AUTO and source_id not in self._wanted:
                if now - session.last_access > _AUTO_TIMEOUT:
                    logger.info("Auto-stopping transient camera: %s (%.0fs idle)", session.device_name, now - session.last_access)
                    session.stop()
                    self._sessions.pop(source_id, None)
                continue
            # "on" cameras with no active viewers: long timeout
            if session.ref_count <= 0:
                if now - session.last_access > _IDLE_TIMEOUT:
                    logger.info("Auto-stopping idle camera: %s", session.device_name)
                    session.stop()
                    del self._sessions[source_id]


def _avf_start_capture(device_uid: str, session_ref: _CameraSession) -> bool:
    """Start native AVFoundation capture for a camera.

    Creates a capture session with a delegate that buffers frames
    directly into the _CameraSession._latest_frame field.
    Returns True on success.
    """
    if sys.platform != "darwin":
        return False
    try:
        import AVFoundation
        import CoreVideo
        import objc
        from Foundation import NSObject

        devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(
            AVFoundation.AVMediaTypeVideo)
        device = None
        for d in devices:
            if str(d.uniqueID()) == device_uid:
                device = d
                break
        if device is None:
            return False

        session = AVFoundation.AVCaptureSession.alloc().init()
        session.setSessionPreset_(AVFoundation.AVCaptureSessionPresetHigh)

        inp, err = AVFoundation.AVCaptureDeviceInput.deviceInputWithDevice_error_(device, None)
        if not inp:
            return False
        session.addInput_(inp)

        output = AVFoundation.AVCaptureVideoDataOutput.alloc().init()
        output.setAlwaysDiscardsLateVideoFrames_(True)
        output.setVideoSettings_({
            str(CoreVideo.kCVPixelBufferPixelFormatTypeKey): int(CoreVideo.kCVPixelFormatType_32BGRA),
        })

        # Create delegate that receives sample buffers
        delegate = _get_avf_delegate_class().alloc().init()
        delegate.camera_session = session_ref

        # Dispatch queue for frame callbacks
        queue = objc.ObjCClass("OS_dispatch_queue").alloc()
        from libdispatch import dispatch_queue_create
        queue = dispatch_queue_create(b"hort.avf.camera", None)
        output.setSampleBufferDelegate_queue_(delegate, queue)

        session.addOutput_(output)
        session.startRunning()

        if not session.isRunning():
            return False

        session_ref._avf_session = session
        session_ref._avf_delegate = delegate
        return True
    except ImportError:
        # Try alternative dispatch queue creation
        try:
            import AVFoundation
            import CoreVideo
            import objc

            devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(
                AVFoundation.AVMediaTypeVideo)
            device = None
            for d in devices:
                if str(d.uniqueID()) == device_uid:
                    device = d
                    break
            if device is None:
                return False

            session = AVFoundation.AVCaptureSession.alloc().init()
            session.setSessionPreset_(AVFoundation.AVCaptureSessionPresetHigh)

            inp, err = AVFoundation.AVCaptureDeviceInput.deviceInputWithDevice_error_(device, None)
            if not inp:
                return False
            session.addInput_(inp)

            output = AVFoundation.AVCaptureVideoDataOutput.alloc().init()
            output.setAlwaysDiscardsLateVideoFrames_(True)
            output.setVideoSettings_({
                str(CoreVideo.kCVPixelBufferPixelFormatTypeKey): int(CoreVideo.kCVPixelFormatType_32BGRA),
            })

            delegate = _get_avf_delegate_class().alloc().init()
            delegate.camera_session = session_ref

            # Use None queue = main queue
            output.setSampleBufferDelegate_queue_(delegate, None)
            session.addOutput_(output)
            session.startRunning()

            if not session.isRunning():
                return False

            session_ref._avf_session = session
            session_ref._avf_delegate = delegate
            return True
        except Exception:
            logger.exception("AVFoundation capture failed for UID %s", device_uid)
            return False
    except Exception:
        logger.exception("AVFoundation capture failed for UID %s", device_uid)
        return False


_AVF_DELEGATE_CLASS: Any = None

def _get_avf_delegate_class() -> Any:
    """Create (once) an ObjC class that receives AVCaptureVideoDataOutput frames."""
    global _AVF_DELEGATE_CLASS
    if _AVF_DELEGATE_CLASS is not None:
        return _AVF_DELEGATE_CLASS

    import objc
    from Foundation import NSObject

    class _HortAVFDelegate(NSObject):
        """Receives sample buffers from AVCaptureVideoDataOutput.

        Converts each frame to WebP and stores in the parent _CameraSession.
        """
        camera_session = objc.ivar()

        @objc.typedSelector(b"v@:@@@")
        def captureOutput_didOutputSampleBuffer_fromConnection_(self, output, sample_buffer, connection):
            session = self.camera_session
            if session is None or not session._running:
                return
            try:
                import CoreVideo
                from PIL import Image

                pixel_buffer = CoreVideo.CMSampleBufferGetImageBuffer(sample_buffer)
                if pixel_buffer is None:
                    return
                CoreVideo.CVPixelBufferLockBaseAddress(pixel_buffer, CoreVideo.kCVPixelBufferLock_ReadOnly)
                try:
                    base = CoreVideo.CVPixelBufferGetBaseAddress(pixel_buffer)
                    w = CoreVideo.CVPixelBufferGetWidth(pixel_buffer)
                    h = CoreVideo.CVPixelBufferGetHeight(pixel_buffer)
                    stride = CoreVideo.CVPixelBufferGetBytesPerRow(pixel_buffer)

                    # BGRA data → PIL Image
                    import ctypes
                    buf = (ctypes.c_uint8 * (stride * h)).from_address(int(base))
                    pil = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", stride, 1)
                    pil = pil.convert("RGB")

                    out = io.BytesIO()
                    pil.save(out, format="WEBP", quality=80, method=2)
                    pil.close()
                    webp = out.getvalue()
                    out.close()

                    with session._lock:
                        session._latest_frame = webp
                    session._width = w
                    session._height = h

                    # FPS tracking
                    session._frame_count = getattr(session, '_frame_count', 0) + 1
                    elapsed = time.monotonic() - getattr(session, '_fps_start', time.monotonic())
                    if elapsed > 1.0:
                        session._fps = session._frame_count / elapsed
                        session._frame_count = 0
                        session._fps_start = time.monotonic()
                finally:
                    CoreVideo.CVPixelBufferUnlockBaseAddress(pixel_buffer, CoreVideo.kCVPixelBufferLock_ReadOnly)
            except Exception:
                pass  # frame drop is fine

    _AVF_DELEGATE_CLASS = _HortAVFDelegate
    return _AVF_DELEGATE_CLASS


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
