"""Binary WebSocket stream transport for window capture.

Architecture:
- **Control WS** carries ALL non-video traffic: input events, config, commands, ACKs
- **Stream WS** carries ONLY video frames: binary data, nothing else
- Client ACKs frames via control WS. Server pauses if >1s of unACKed frames.
- Multiple streams supported: stream_id prefixes each frame (multi-monitor, webcam).

Supports two codecs:
- **JPEG** (default): each frame is independent. Simple, universal.
- **VP8/VP9**: WebM segments with inter-frame compression. ~10x smaller.

Works identically over LAN, proxy, and P2P.

Frame format (binary):
    [stream_id: 2 bytes, big-endian][seq: 4 bytes, big-endian][data: N bytes]

ACK format (JSON via control WS):
    {"type": "stream_ack", "stream_id": 0, "seq": 1234}
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import struct
import time
from typing import TYPE_CHECKING, Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from hort.ext.types import PlatformProvider
from hort.targets import TargetRegistry

if TYPE_CHECKING:
    from hort.session import HortRegistry, HortSessionEntry

logger = logging.getLogger(__name__)

# Frame header: stream_id (2) + seq (4) + timestamp_ms (4) = 10 bytes
# timestamp_ms = milliseconds since stream start (uint32, wraps at ~49 days)
FRAME_HEADER = struct.Struct("!HII")
FRAME_HEADER_SIZE = FRAME_HEADER.size  # 10 bytes

# Max unACKed time/frames before pausing
MAX_UNACKED_SECONDS = 1.0
MAX_UNACKED_FRAMES = 5  # never more than 5 frames in flight


class StreamState:
    """Per-stream ACK tracking and flow control.

    The server tracks which frames have been sent and which the client
    has acknowledged. If the gap exceeds MAX_UNACKED_SECONDS, the server
    pauses sending until the client catches up.
    """

    def __init__(self, stream_id: int = 0) -> None:
        self.stream_id = stream_id
        self.seq = 0
        self.last_acked_seq = 0
        self.last_acked_time = time.monotonic()
        self.last_sent_time = time.monotonic()
        self.stream_start = time.monotonic()
        self.paused = False

    def next_seq(self) -> int:
        """Get and increment the sequence number."""
        s = self.seq
        self.seq += 1
        self.last_sent_time = time.monotonic()
        return s

    def timestamp_ms(self) -> int:
        """Milliseconds since stream start (uint32)."""
        return int((time.monotonic() - self.stream_start) * 1000) & 0xFFFFFFFF

    def ack(self, seq: int) -> None:
        """Record that the client has rendered up to this sequence."""
        if seq > self.last_acked_seq:
            self.last_acked_seq = seq
            self.last_acked_time = time.monotonic()
            self.paused = False

    @property
    def should_pause(self) -> bool:
        """True if we should stop sending (client too far behind).

        Pauses when:
        - More than MAX_UNACKED_FRAMES in flight, OR
        - More than MAX_UNACKED_SECONDS since last ACK

        Auto-recovers after 5s of no ACKs by resetting state.
        """
        if self.seq == 0:
            return False

        unacked_frames = self.seq - self.last_acked_seq
        unacked_time = time.monotonic() - self.last_acked_time

        # Auto-recovery: if stuck for >5s, ACKs are probably dead.
        if unacked_time > 5.0:
            logger.info("stream %d auto-recovery: %.1fs unACKed (%d frames), resetting",
                        self.stream_id, unacked_time, unacked_frames)
            self.last_acked_seq = self.seq
            self.last_acked_time = time.monotonic()
            self.paused = False
            return False

        # Pause if too many frames in flight or too much time
        if unacked_frames > MAX_UNACKED_FRAMES or (
            unacked_time > MAX_UNACKED_SECONDS and unacked_frames > 1
        ):
            if not self.paused:
                logger.debug("stream %d paused: %d unACKed frames, %.1fs",
                             self.stream_id, unacked_frames, unacked_time)
                self.paused = True
            return True

        if self.paused:
            self.paused = False
        return False

    def pack_header(self, seq: int) -> bytes:
        """Pack the 10-byte frame header with timestamp."""
        return FRAME_HEADER.pack(self.stream_id, seq, self.timestamp_ms())


def _effective_max_width(screen_width: int, screen_dpr: float, max_width: int) -> int:
    if screen_width > 0 and screen_dpr > 0:
        client_pixels = int(screen_width * screen_dpr)
        return min(max_width, client_pixels)
    return max_width


def _get_provider(target_id: str = "") -> PlatformProvider | None:
    registry = TargetRegistry.get()
    if target_id:
        return registry.get_provider(target_id)
    return registry.get_default()


class _VideoEncoder:
    """VP8/VP9 encoder wrapper. Lazy-initialized on first frame."""

    def __init__(self, codec: str, fps: int, bitrate: int = 2_000_000) -> None:
        self._codec = codec
        self._fps = fps
        self._bitrate = bitrate
        self._encoder: Any = None
        self._width = 0
        self._height = 0
        self._init_sent = False

    def encode(self, pil_image: Any) -> tuple[bytes | None, bytes | None]:
        """Returns (init_segment_or_None, frame_data_or_None)."""
        import av

        w = pil_image.width - (pil_image.width % 2)
        h = pil_image.height - (pil_image.height % 2)

        if w != self._width or h != self._height:
            self._close()
            self._width = w
            self._height = h
            self._init_sent = False

        if self._encoder is None:
            self._encoder = self._create_encoder()

        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        if pil_image.width != self._width or pil_image.height != self._height:
            from PIL import Image
            pil_image = pil_image.resize((self._width, self._height), Image.Resampling.LANCZOS)

        frame = av.VideoFrame.from_image(pil_image)
        frame.pts = self._encoder["frame_count"]
        self._encoder["frame_count"] += 1

        buf = self._encoder["output"]
        buf.seek(0)
        buf.truncate()
        for packet in self._encoder["stream"].encode(frame):
            self._encoder["container"].mux(packet)
        frame_data = buf.getvalue()

        init_segment = None
        if not self._init_sent:
            init_segment = self._get_init_segment()
            self._init_sent = True

        return init_segment, frame_data if frame_data else None

    def _create_encoder(self) -> dict[str, Any]:
        import av
        codec_lib = "libvpx" if self._codec == "vp8" else "libvpx-vp9"
        output = io.BytesIO()
        container = av.open(output, mode="w", format="webm", options={"live": "1"})
        stream = container.add_stream(codec_lib, rate=self._fps)
        stream.width = self._width
        stream.height = self._height
        stream.bit_rate = self._bitrate
        stream.pix_fmt = "yuv420p"
        opts = {"cpu-used": "8", "deadline": "realtime", "lag-in-frames": "0"}
        if self._codec == "vp9":
            opts["row-mt"] = "1"
        stream.options = opts
        return {"container": container, "stream": stream, "output": output, "frame_count": 0}

    def _get_init_segment(self) -> bytes:
        import av
        from PIL import Image as _Image
        buf = io.BytesIO()
        codec_lib = "libvpx" if self._codec == "vp8" else "libvpx-vp9"
        container = av.open(buf, mode="w", format="webm")
        stream = container.add_stream(codec_lib, rate=self._fps)
        stream.width = self._width
        stream.height = self._height
        stream.pix_fmt = "yuv420p"
        black = _Image.new("RGB", (self._width, self._height), (0, 0, 0))
        frame = av.VideoFrame.from_image(black)
        frame.pts = 0
        for pkt in stream.encode(frame):
            container.mux(pkt)
        for pkt in stream.encode():
            container.mux(pkt)
        container.close()
        return buf.getvalue()

    def _close(self) -> None:
        if self._encoder:
            try:
                for pkt in self._encoder["stream"].encode():
                    self._encoder["container"].mux(pkt)
                self._encoder["container"].close()
            except Exception:
                pass
            self._encoder = None

    def close(self) -> None:
        self._close()


async def run_stream(
    websocket: WebSocket,
    session_id: str,
    registry: HortRegistry,
) -> None:
    """Run the binary stream WebSocket. Video frames only.

    Frames are prefixed with a 6-byte header (stream_id + seq).
    The client ACKs via the control WebSocket. The server pauses
    if unACKed frames exceed 1 second.
    """
    entry = registry.get_session(session_id)
    if not entry:
        await websocket.close(code=4004, reason="Session not found")
        return

    if entry.stream_ws is not None:
        try:
            await entry.stream_ws.close(code=4001, reason="Superseded")
        except Exception:
            pass

    await websocket.accept()
    entry.stream_ws = websocket
    entry.observer_id = registry.next_observer_id()

    # Stream state for flow control (stream_id=0 = primary display)
    stream_state = StreamState(stream_id=0)
    # Store on entry so the control WS can deliver ACKs
    if not hasattr(entry, "stream_states"):
        entry.stream_states = {}  # type: ignore[attr-defined]
    entry.stream_states[0] = stream_state  # type: ignore[attr-defined]

    prev_window_id: int = 0
    prev_codec: str = ""
    frame_count = 0
    video_encoder: _VideoEncoder | None = None

    _frame_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)

    async def _send_loop() -> None:
        while True:
            frame_data = await _frame_queue.get()
            if frame_data is None:
                break
            try:
                await websocket.send_bytes(frame_data)
            except Exception:
                break
            finally:
                del frame_data

    send_task = asyncio.create_task(_send_loop())

    try:
        while True:
            config = entry.stream_config
            if config is None:
                await asyncio.sleep(0.1)
                continue

            # Flow control: pause if client is too far behind
            if stream_state.should_pause:
                await asyncio.sleep(0.05)
                continue

            provider = _get_provider(entry.active_target_id)
            if provider is None:
                await asyncio.sleep(1.0)
                continue

            if config.window_id != prev_window_id:
                logger.info("Switching to window %d (target=%s)", config.window_id, entry.active_target_id)
                if config.window_id >= 0:
                    _raise_window(config.window_id, provider)
                prev_window_id = config.window_id

            # Switch encoder when codec changes
            codec = config.codec if config.codec in ("vp8", "vp9") else "jpeg"
            if codec != prev_codec:
                if video_encoder:
                    video_encoder.close()
                    video_encoder = None
                if codec in ("vp8", "vp9"):
                    video_encoder = _VideoEncoder(codec, config.fps)
                prev_codec = codec

            effective_width = _effective_max_width(
                config.screen_width, config.screen_dpr, config.max_width
            )

            # Capture
            t0 = time.monotonic()
            if codec == "jpeg":
                frame = provider.capture_window(
                    config.window_id, effective_width, config.quality
                )
            else:
                frame = await _capture_pil(provider, config.window_id, effective_width)
            capture_ms = (time.monotonic() - t0) * 1000

            frame_count += 1
            if frame_count % 100 == 0:
                ss = stream_state
                logger.info(
                    "Stream [%s]: %d frames, capture %.0fms, window=%d, "
                    "seq=%d, acked=%d, paused=%s",
                    codec, frame_count, capture_ms, config.window_id,
                    ss.seq, ss.last_acked_seq, ss.paused,
                )

            if frame is None:
                if entry.websocket is not None:
                    try:
                        await entry.websocket.send_text(
                            json.dumps({"type": "stream_error", "error": "Window not found"})
                        )
                    except Exception:
                        pass
                await asyncio.sleep(1.0)
                entry.stream_config = None
                prev_window_id = 0
                continue

            # Build frame with header
            seq = stream_state.next_seq()
            header = stream_state.pack_header(seq)

            if codec == "jpeg":
                _enqueue(header + frame, _frame_queue)
            else:
                assert video_encoder is not None
                init_seg, frame_data = video_encoder.encode(frame)
                frame.close()
                if init_seg:
                    # Init segment gets seq 0 (no ACK needed, but keeps header format consistent)
                    _enqueue(header + init_seg, _frame_queue)
                if frame_data:
                    _enqueue(header + frame_data, _frame_queue)

            # Adaptive sleep: if capture took longer than frame budget,
            # don't try to catch up — just move on to the next frame.
            # This prevents frame pile-up when fps is set higher than
            # the system can handle (e.g. 60fps with 70ms captures).
            frame_budget = 1.0 / config.fps
            sleep_time = frame_budget - (capture_ms / 1000.0)
            if sleep_time > 0.001:
                await asyncio.sleep(sleep_time)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("Stream error for session %s: %s", session_id[:8], e)
    finally:
        try:
            _frame_queue.put_nowait(None)
        except asyncio.QueueFull:
            try:
                _frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            _frame_queue.put_nowait(None)
        send_task.cancel()
        entry.stream_ws = None
        entry.stream_config = None  # force fresh config on reconnect
        entry.observer_id = 0
        if hasattr(entry, "stream_states"):
            entry.stream_states.pop(0, None)  # type: ignore[attr-defined]
        if video_encoder:
            video_encoder.close()
        logger.info("Stream ended for session %s (%d frames)", session_id[:8], frame_count)


def handle_stream_ack(entry: Any, msg: dict[str, Any]) -> None:
    """Handle a stream_ack message from the control WebSocket.

    Called by the controller when it receives:
    {"type": "stream_ack", "stream_id": 0, "seq": 1234}
    """
    stream_id = msg.get("stream_id", 0)
    seq = msg.get("seq", 0)
    states = getattr(entry, "stream_states", {})
    state = states.get(stream_id)
    if state:
        state.ack(seq)


def _enqueue(data: bytes, queue: asyncio.Queue[bytes | None]) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(data)


async def _capture_pil(provider: PlatformProvider, window_id: int, max_width: int) -> Any:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _capture_pil_sync, provider, window_id, max_width)


def _capture_pil_sync(provider: PlatformProvider, window_id: int, max_width: int) -> Any:
    try:
        from hort.screen import (
            DESKTOP_WINDOW_ID,
            _cgimage_to_pil,
            _raw_capture,
            _raw_capture_desktop,
        )
    except ImportError:
        return None

    if window_id == DESKTOP_WINDOW_ID:
        cg_image = _raw_capture_desktop()
    else:
        cg_image = _raw_capture(window_id)

    if cg_image is None:
        return None

    try:
        pil_image = _cgimage_to_pil(cg_image)
    finally:
        del cg_image

    if pil_image is None:
        return None

    if pil_image.width > max_width:
        ratio = max_width / pil_image.width
        new_height = int(pil_image.height * ratio)
        from PIL import Image
        resized = pil_image.resize((max_width, new_height), Image.Resampling.LANCZOS)
        pil_image.close()
        return resized

    return pil_image


def _raise_window(window_id: int, provider: PlatformProvider) -> None:
    t0 = time.monotonic()
    windows = provider.list_windows()
    list_ms = (time.monotonic() - t0) * 1000
    win = next((w for w in windows if w.window_id == window_id), None)
    if not win or not win.owner_pid:
        return
    t1 = time.monotonic()
    provider.activate_app(win.owner_pid, bounds=win.bounds)
    activate_ms = (time.monotonic() - t1) * 1000
    logger.info("_raise_window: %s/%s pid=%d list=%.0fms activate=%.0fms",
                win.owner_name, win.window_name[:30], win.owner_pid, list_ms, activate_ms)
