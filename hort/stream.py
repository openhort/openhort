"""Binary WebSocket stream transport for window capture.

Supports two codecs:
- **JPEG** (default): each frame independent, drop-safe, zoomable/pannable
- **WebP**: VP8-based, ~30-40% smaller than JPEG, same drop-safe rendering
- **VP8/VP9**: real video stream via WebM/MSE — inter-frame compression,
  smooth 60fps, hardware decode. NOT drop-safe — uses ordered delivery
  with ACK-based flow control instead of single-slot queue.

Frame format (binary):
    [stream_id: 2 bytes][seq: 4 bytes][timestamp_ms: 4 bytes][data: N bytes]

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

FRAME_HEADER = struct.Struct("!HII")  # stream_id(2) + seq(4) + ts_ms(4) = 10 bytes
FRAME_HEADER_SIZE = FRAME_HEADER.size

MAX_UNACKED_SECONDS = 1.0
MAX_UNACKED_FRAMES = 5
MAX_UNACKED_FRAMES_VIDEO = 2  # tighter for VP8/VP9 (larger frames)


class StreamState:
    """Per-stream ACK tracking and flow control."""

    def __init__(self, stream_id: int = 0, is_video: bool = False) -> None:
        self.stream_id = stream_id
        self.seq = 0
        self.last_acked_seq = 0
        self.last_acked_time = time.monotonic()
        self.stream_start = time.monotonic()
        self.paused = False
        self._max_unacked = MAX_UNACKED_FRAMES_VIDEO if is_video else MAX_UNACKED_FRAMES

    def next_seq(self) -> int:
        s = self.seq
        self.seq += 1
        return s

    def timestamp_ms(self) -> int:
        return int((time.monotonic() - self.stream_start) * 1000) & 0xFFFFFFFF

    def ack(self, seq: int) -> None:
        if seq > self.last_acked_seq:
            self.last_acked_seq = seq
            self.last_acked_time = time.monotonic()
            self.paused = False

    @property
    def should_pause(self) -> bool:
        if self.seq == 0:
            return False
        unacked = self.seq - self.last_acked_seq
        unacked_time = time.monotonic() - self.last_acked_time

        if unacked_time > 5.0:
            logger.info("stream %d auto-recovery: %.1fs unACKed (%d frames)",
                        self.stream_id, unacked_time, unacked)
            self.last_acked_seq = self.seq
            self.last_acked_time = time.monotonic()
            self.paused = False
            return False

        if unacked > self._max_unacked or (unacked_time > MAX_UNACKED_SECONDS and unacked > 1):
            if not self.paused:
                logger.debug("stream %d paused: %d unACKed, %.1fs",
                             self.stream_id, unacked, unacked_time)
                self.paused = True
            return True

        if self.paused:
            self.paused = False
        return False

    def pack_header(self, seq: int) -> bytes:
        return FRAME_HEADER.pack(self.stream_id, seq, self.timestamp_ms())


class _VideoEncoder:
    """VP8/VP9 WebM encoder for real video streaming via MSE."""

    def __init__(self, codec: str, fps: int, bitrate: int = 2_000_000) -> None:
        self._codec = codec
        self._fps = fps
        self._bitrate = bitrate
        self._enc: Any = None
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
            self._width, self._height = w, h
            self._init_sent = False

        if self._enc is None:
            self._enc = self._create()

        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        if pil_image.width != self._width or pil_image.height != self._height:
            from PIL import Image
            pil_image = pil_image.resize((self._width, self._height), Image.Resampling.LANCZOS)

        frame = av.VideoFrame.from_image(pil_image)
        # Sequential PTS with rate=10 → each frame = 100ms of video time
        frame.pts = self._enc["fc"]
        self._enc["fc"] += 1

        buf = self._enc["buf"]
        buf.seek(0)
        buf.truncate()
        for pkt in self._enc["stream"].encode(frame):
            self._enc["container"].mux(pkt)
        frame_data = buf.getvalue() or None

        init_seg = None
        if not self._init_sent:
            init_seg = self._make_init()
            self._init_sent = True

        return init_seg, frame_data

    def _create(self) -> dict[str, Any]:
        import av
        codec_lib = "libvpx" if self._codec == "vp8" else "libvpx-vp9"
        buf = io.BytesIO()
        # cluster_size_limit=0 forces one frame per cluster → immediate flush
        container = av.open(buf, mode="w", format="webm",
                            options={"live": "1", "cluster_size_limit": "0"})
        # Rate=10 (conservative) — ensures the video never plays faster than
        # frames arrive. Each frame = 100ms of video time. Real capture is
        # ~80-100ms so the buffer stays stable (no freeze/refill cycle).
        stream = container.add_stream(codec_lib, rate=10)
        stream.width = self._width
        stream.height = self._height
        stream.bit_rate = self._bitrate
        stream.pix_fmt = "yuv420p"
        opts = {"cpu-used": "8", "deadline": "realtime", "lag-in-frames": "0"}
        if self._codec == "vp9":
            opts["row-mt"] = "1"
        stream.options = opts
        return {"container": container, "stream": stream, "buf": buf, "fc": 0, "start": 0}

    def _make_init(self) -> bytes:
        """Generate MSE-compatible init segment (EBML + Segment + Tracks, NO clusters).

        The Segment size is patched to 'unknown' so MSE accepts appended clusters.
        """
        import av
        from PIL import Image as _Image

        buf = io.BytesIO()
        codec_lib = "libvpx" if self._codec == "vp8" else "libvpx-vp9"
        c = av.open(buf, mode="w", format="webm")
        s = c.add_stream(codec_lib, rate=10)
        s.width, s.height, s.pix_fmt = self._width, self._height, "yuv420p"
        # Encode one frame to force header + tracks to be written
        black = _Image.new("RGB", (self._width, self._height), (0, 0, 0))
        f = av.VideoFrame.from_image(black)
        f.pts = 0
        for pkt in s.encode(f):
            c.mux(pkt)
        for pkt in s.encode():
            c.mux(pkt)
        c.close()

        data = bytearray(buf.getvalue())

        # Find the Cluster element (0x1F43B675) and truncate before it
        cluster_marker = b'\x1f\x43\xb6\x75'
        cluster_pos = data.find(cluster_marker)
        if cluster_pos > 0:
            data = data[:cluster_pos]

        # Patch the Segment size to "unknown" (0x01FFFFFFFFFFFFFF)
        # so MSE accepts dynamically appended clusters
        segment_marker = b'\x18\x53\x80\x67'
        seg_pos = data.find(segment_marker)
        if seg_pos >= 0:
            # Segment ID is 4 bytes, followed by size (EBML variable int)
            # Replace the size with 8-byte "unknown" marker
            size_start = seg_pos + 4
            # Find where the size bytes are and replace with unknown
            data[size_start:size_start + 8] = b'\x01\xff\xff\xff\xff\xff\xff\xff'

        return bytes(data)

    def _close(self) -> None:
        if self._enc:
            try:
                for pkt in self._enc["stream"].encode():
                    self._enc["container"].mux(pkt)
                self._enc["container"].close()
            except Exception:
                pass
            self._enc = None

    def close(self) -> None:
        self._close()


def _effective_max_width(screen_width: int, screen_dpr: float, max_width: int) -> int:
    if screen_width > 0 and screen_dpr > 0:
        return min(max_width, int(screen_width * screen_dpr))
    return max_width


def _get_provider(target_id: str = "") -> PlatformProvider | None:
    registry = TargetRegistry.get()
    return registry.get_provider(target_id) if target_id else registry.get_default()


async def run_stream(
    websocket: WebSocket,
    session_id: str,
    registry: HortRegistry,
) -> None:
    """Run the binary stream WebSocket."""
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

    prev_window_id: int = 0
    prev_codec: str = ""
    prev_quality: int = 0
    frame_count = 0
    video_encoder: _VideoEncoder | None = None
    stream_state: StreamState | None = None

    # For JPEG/WebP: single-slot queue (drop old frames)
    # For VP8/VP9: ordered queue (never drop — ACK flow control limits in-flight)
    _jpeg_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)
    _video_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=4)

    async def _send_loop(q: asyncio.Queue[bytes | None]) -> None:
        while True:
            data = await q.get()
            if data is None:
                break
            try:
                await websocket.send_bytes(data)
            except Exception:
                break

    active_queue = _jpeg_queue
    send_task = asyncio.create_task(_send_loop(active_queue))

    if not hasattr(entry, "stream_states"):
        entry.stream_states = {}  # type: ignore[attr-defined]

    try:
        while True:
            config = entry.stream_config
            if config is None:
                await asyncio.sleep(0.1)
                continue

            codec = config.codec if config.codec in ("vp8", "vp9", "webp") else "jpeg"
            is_video = codec in ("vp8", "vp9")

            # Recreate encoder on codec or quality change, KEEP seq continuous
            quality_changed = is_video and config.quality != prev_quality
            if codec != prev_codec or quality_changed:
                if video_encoder:
                    video_encoder.close()
                    video_encoder = None
                if is_video:
                    # Map quality (10-100) to bitrate (500Kbps - 8Mbps)
                    bitrate = int(500_000 + (config.quality / 100) * 7_500_000)
                    video_encoder = _VideoEncoder(codec, config.fps, bitrate=bitrate)

                send_task.cancel()
                if is_video:
                    _video_queue = asyncio.Queue(maxsize=4)
                    active_queue = _video_queue
                else:
                    _jpeg_queue = asyncio.Queue(maxsize=1)
                    active_queue = _jpeg_queue
                send_task = asyncio.create_task(_send_loop(active_queue))

                # Keep seq continuous (DON'T create new StreamState)
                # This ensures the init segment has a higher seq than
                # any previously rendered JPEG frame
                if stream_state is None:
                    stream_state = StreamState(stream_id=0, is_video=is_video)
                else:
                    stream_state._max_unacked = MAX_UNACKED_FRAMES_VIDEO if is_video else MAX_UNACKED_FRAMES
                entry.stream_states[0] = stream_state  # type: ignore[attr-defined]
                prev_codec = codec
                prev_quality = config.quality
                logger.info("Stream codec → %s q=%d (seq=%d)", codec, config.quality, stream_state.seq)
                # Notify client to reset frame tracking (seq restarts from 0)
                if entry.websocket is not None:
                    try:
                        await entry.websocket.send_text(
                            json.dumps({"type": "codec_change", "codec": codec})
                        )
                    except Exception:
                        pass

            assert stream_state is not None

            if stream_state.should_pause:
                await asyncio.sleep(0.05)
                continue

            provider = _get_provider(entry.active_target_id)
            if provider is None:
                await asyncio.sleep(1.0)
                continue

            if config.window_id != prev_window_id:
                logger.info("Stream window → %d", config.window_id)
                if config.window_id >= 0:
                    _raise_window(config.window_id, provider)
                prev_window_id = config.window_id

            effective_width = _effective_max_width(
                config.screen_width, config.screen_dpr, config.max_width
            )

            # Capture
            t0 = time.monotonic()
            if is_video:
                # VP8/VP9: need PIL image for video encoder
                pil_image = await _capture_pil(provider, config.window_id, effective_width)
                if pil_image is None:
                    await _handle_capture_fail(entry, config)
                    prev_window_id = 0
                    continue
            else:
                # JPEG/WebP: capture as JPEG bytes via provider
                frame_bytes = provider.capture_window(
                    config.window_id, effective_width, config.quality
                )
                if frame_bytes is None:
                    await _handle_capture_fail(entry, config)
                    prev_window_id = 0
                    continue

                if codec == "webp":
                    from PIL import Image as _Img
                    pil = _Img.open(io.BytesIO(frame_bytes))
                    wbuf = io.BytesIO()
                    pil.save(wbuf, format="WEBP", quality=config.quality, method=0)
                    pil.close()
                    frame_bytes = wbuf.getvalue()

            capture_ms = (time.monotonic() - t0) * 1000
            frame_count += 1

            if is_video:
                # VP8/VP9: encode to WebM, send init segment directly, frame via queue
                assert video_encoder is not None
                init_seg, frame_data = video_encoder.encode(pil_image)
                pil_image.close()
                if init_seg:
                    seq = stream_state.next_seq()
                    header = stream_state.pack_header(seq)
                    logger.info("VP8 init: %dB seq=%d", len(init_seg), seq)
                    try:
                        await websocket.send_bytes(header + init_seg)
                    except Exception:
                        break
                if frame_data:
                    seq = stream_state.next_seq()
                    header = stream_state.pack_header(seq)
                    _enqueue(header + frame_data, active_queue)
            else:
                seq = stream_state.next_seq()
                header = stream_state.pack_header(seq)
                _enqueue(header + frame_bytes, active_queue)

            if frame_count % 100 == 0:
                logger.info("Stream [%s]: %d frames, %.0fms, seq=%d acked=%d",
                            codec, frame_count, capture_ms,
                            stream_state.seq, stream_state.last_acked_seq)

            sleep_time = (1.0 / config.fps) - (capture_ms / 1000.0)
            if sleep_time > 0.001:
                await asyncio.sleep(sleep_time)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("Stream error: %s", e)
    finally:
        try:
            active_queue.put_nowait(None)
        except asyncio.QueueFull:
            try:
                active_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            active_queue.put_nowait(None)
        send_task.cancel()
        entry.stream_ws = None
        entry.stream_config = None
        entry.observer_id = 0
        if hasattr(entry, "stream_states"):
            entry.stream_states.pop(0, None)  # type: ignore[attr-defined]
        if video_encoder:
            video_encoder.close()
        logger.info("Stream ended (%d frames)", frame_count)


async def _handle_capture_fail(entry: Any, config: Any) -> None:
    if entry.websocket is not None:
        try:
            await entry.websocket.send_text(
                json.dumps({"type": "stream_error", "error": "Window not found"})
            )
        except Exception:
            pass
    await asyncio.sleep(1.0)
    entry.stream_config = None


def handle_stream_ack(entry: Any, msg: dict[str, Any]) -> None:
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
    return await asyncio.get_event_loop().run_in_executor(
        None, _capture_pil_sync, provider, window_id, max_width
    )


def _capture_pil_sync(provider: PlatformProvider, window_id: int, max_width: int) -> Any:
    try:
        from hort.screen import (
            DESKTOP_WINDOW_ID, _cgimage_to_pil, _raw_capture, _raw_capture_desktop,
        )
    except ImportError:
        return None
    cg_image = _raw_capture_desktop() if window_id == DESKTOP_WINDOW_ID else _raw_capture(window_id)
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
        from PIL import Image
        resized = pil_image.resize((max_width, int(pil_image.height * ratio)), Image.Resampling.LANCZOS)
        pil_image.close()
        return resized
    return pil_image


def _raise_window(window_id: int, provider: PlatformProvider) -> None:
    windows = provider.list_windows()
    win = next((w for w in windows if w.window_id == window_id), None)
    if win and win.owner_pid:
        provider.activate_app(win.owner_pid, bounds=win.bounds)
