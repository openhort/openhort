"""Video stream track for WebRTC — feeds screen captures as VP8/VP9 frames.

Implements an aiortc VideoStreamTrack that captures the screen at a
configurable FPS and resolution, producing av.VideoFrame objects that
aiortc encodes and sends over the WebRTC video track.

For P2P mode: aiortc encodes to VP8 (native) and sends via RTP.
For proxy mode: the same frames can be encoded to VP9 WebM via av.

Usage::

    track = ScreenCaptureTrack(fps=30, max_width=1920, codec='vp8')
    track.set_window(window_id=101)

    # Add to WebRTC peer
    peer._pc.addTrack(track)
"""

from __future__ import annotations

import asyncio
import fractions
import logging
import time
from typing import Any

import av
from aiortc import VideoStreamTrack

logger = logging.getLogger(__name__)

# Default test pattern dimensions
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


class ScreenCaptureTrack(VideoStreamTrack):
    """VideoStreamTrack that captures screen content.

    Produces av.VideoFrame objects at the configured FPS. The frames
    are then encoded by aiortc's VP8 encoder for WebRTC transport.

    Falls back to a test pattern when no capture provider is available
    (useful for testing without macOS screen recording permission).
    """

    kind = "video"

    def __init__(
        self,
        fps: int = 15,
        max_width: int = 1920,
        quality: str = "realtime",
    ) -> None:
        super().__init__()
        self._fps = fps
        self._max_width = max_width
        self._quality = quality
        self._window_id: int | None = None
        self._capture_fn: Any = None  # callable(window_id, max_width) -> PIL.Image | None
        self._frame_count = 0
        self._start_time: float | None = None
        self._last_capture_ms = 0.0

    def set_capture_function(self, fn: Any) -> None:
        """Set the capture function: fn(window_id, max_width) -> PIL.Image | None."""
        self._capture_fn = fn

    def set_window(self, window_id: int) -> None:
        """Set which window to capture."""
        self._window_id = window_id

    @property
    def fps(self) -> int:
        return self._fps

    @fps.setter
    def fps(self, value: int) -> None:
        self._fps = max(1, min(60, value))

    async def recv(self) -> av.VideoFrame:
        """Called by aiortc to get the next video frame.

        aiortc calls this at the negotiated rate. We pace to our
        target FPS and return an av.VideoFrame.
        """
        if self._start_time is None:
            self._start_time = time.time()

        # Pace to target FPS
        target_time = self._start_time + (self._frame_count / self._fps)
        now = time.time()
        if target_time > now:
            await asyncio.sleep(target_time - now)

        # Capture frame
        frame = await self._capture_frame()

        # Set timestamps
        pts = int(self._frame_count * (90000 / self._fps))  # 90kHz clock
        frame.pts = pts
        frame.time_base = fractions.Fraction(1, 90000)

        self._frame_count += 1
        return frame

    async def _capture_frame(self) -> av.VideoFrame:
        """Capture a screen frame, or generate a test pattern."""
        if self._capture_fn and self._window_id is not None:
            try:
                t0 = time.monotonic()
                pil_image = await asyncio.get_event_loop().run_in_executor(
                    None, self._capture_fn, self._window_id, self._max_width
                )
                self._last_capture_ms = (time.monotonic() - t0) * 1000

                if pil_image is not None:
                    # Convert PIL Image to av.VideoFrame
                    if pil_image.mode != "RGB":
                        pil_image = pil_image.convert("RGB")
                    frame = av.VideoFrame.from_image(pil_image)
                    pil_image.close()
                    return frame
            except Exception as exc:
                if self._frame_count % 100 == 0:
                    logger.debug("capture error: %s", exc)

        # Fallback: test pattern
        return self._test_pattern()

    def _test_pattern(self) -> av.VideoFrame:
        """Generate a test pattern frame with moving bar."""
        from PIL import Image, ImageDraw

        width = DEFAULT_WIDTH
        height = DEFAULT_HEIGHT

        img = Image.new("RGB", (width, height), color=(26, 26, 46))
        draw = ImageDraw.Draw(img)

        # Moving vertical bar
        bar_x = int((self._frame_count * 5) % width)
        draw.rectangle([bar_x, 0, bar_x + 4, height], fill=(124, 77, 255))

        # Frame counter box
        cx, cy = width // 2, height // 2
        draw.rectangle([cx - 60, cy - 20, cx + 60, cy + 20], fill=(22, 33, 62))

        frame = av.VideoFrame.from_image(img)
        img.close()
        return frame


class ScreenCaptureProvider:
    """Provides screen capture as PIL Images for the video track.

    Wraps the platform provider's capture_window to return PIL Images
    instead of JPEG bytes.
    """

    def __init__(self) -> None:
        self._provider: Any = None

    def set_provider(self, provider: Any) -> None:
        """Set the platform provider (PlatformProvider)."""
        self._provider = provider

    def capture_pil(self, window_id: int, max_width: int) -> Any:
        """Capture a window and return as PIL Image (not JPEG bytes).

        This runs in an executor thread — must be sync.
        """
        if not self._provider:
            return None

        # Use the raw capture path to get PIL image before JPEG encoding
        try:
            from hort.screen import (
                DESKTOP_WINDOW_ID,
                _cgimage_to_pil,
                _raw_capture,
                _raw_capture_desktop,
            )

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

            # Resize if needed
            if pil_image.width > max_width:
                ratio = max_width / pil_image.width
                new_height = int(pil_image.height * ratio)
                from PIL import Image
                resized = pil_image.resize((max_width, new_height), Image.Resampling.LANCZOS)
                pil_image.close()
                return resized

            return pil_image
        except ImportError:
            # Not on macOS or missing dependencies
            return None


class WebMEncoder:
    """Encodes video frames to VP8 or VP9 WebM for the proxy/WebSocket path.

    Produces WebM segments that can be fed to Media Source Extensions
    in the browser.

    Usage::

        encoder = WebMEncoder(codec='vp9', fps=30, width=1920, height=1080)
        for pil_image in frames:
            webm_data = encoder.encode_frame(pil_image)
            # Send webm_data over WebSocket

        header = encoder.get_init_segment()  # WebM header for MSE
        encoder.close()
    """

    def __init__(
        self,
        codec: str = "vp8",
        fps: int = 15,
        width: int = 1280,
        height: int = 720,
        bitrate: int = 2_000_000,
    ) -> None:
        self._codec_name = codec
        self._fps = fps
        self._width = width
        self._height = height
        self._bitrate = bitrate
        self._container: Any = None
        self._stream: Any = None
        self._output: Any = None
        self._frame_count = 0
        self._init_segment: bytes | None = None

        self._setup_encoder()

    def _setup_encoder(self) -> None:
        """Initialize the av encoder and WebM container."""
        import io

        self._output = io.BytesIO()

        codec_lib = "libvpx" if self._codec_name == "vp8" else "libvpx-vp9"

        self._container = av.open(self._output, mode="w", format="webm")
        self._stream = self._container.add_stream(codec_lib, rate=self._fps)
        self._stream.width = self._width
        self._stream.height = self._height
        self._stream.bit_rate = self._bitrate
        self._stream.pix_fmt = "yuv420p"

        # Low-latency settings
        if self._codec_name == "vp8":
            self._stream.options = {
                "cpu-used": "8",  # fastest encoding
                "deadline": "realtime",
                "lag-in-frames": "0",
            }
        else:  # vp9
            self._stream.options = {
                "cpu-used": "8",
                "deadline": "realtime",
                "lag-in-frames": "0",
                "row-mt": "1",  # multi-threaded row encoding
            }

    def encode_frame(self, pil_image: Any) -> bytes:
        """Encode a PIL Image frame and return the WebM data.

        Returns bytes containing the encoded WebM data for this frame.
        May return empty bytes if the encoder is buffering.
        """
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        # Resize if dimensions don't match
        if pil_image.width != self._width or pil_image.height != self._height:
            from PIL import Image
            pil_image = pil_image.resize(
                (self._width, self._height), Image.Resampling.LANCZOS
            )

        frame = av.VideoFrame.from_image(pil_image)
        frame.pts = self._frame_count
        self._frame_count += 1

        # Encode
        self._output.seek(0)
        self._output.truncate()

        for packet in self._stream.encode(frame):
            self._container.mux(packet)

        data = self._output.getvalue()
        return data

    def get_init_segment(self) -> bytes:
        """Get the WebM initialization segment (header).

        Must be sent to the browser before any frame data for MSE.
        Encodes a single black frame to force the header to be written.
        """
        if self._init_segment is not None:
            return self._init_segment

        import io
        from PIL import Image as _Image

        buf = io.BytesIO()
        codec_lib = "libvpx" if self._codec_name == "vp8" else "libvpx-vp9"
        container = av.open(buf, mode="w", format="webm")
        stream = container.add_stream(codec_lib, rate=self._fps)
        stream.width = self._width
        stream.height = self._height
        stream.pix_fmt = "yuv420p"

        # Encode one black frame to force header + first cluster
        black = _Image.new("RGB", (self._width, self._height), (0, 0, 0))
        frame = av.VideoFrame.from_image(black)
        frame.pts = 0
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
        container.close()

        self._init_segment = buf.getvalue()
        return self._init_segment

    def close(self) -> None:
        """Flush and close the encoder."""
        if self._container:
            # Flush
            for packet in self._stream.encode():
                self._container.mux(packet)
            self._container.close()

    @property
    def codec(self) -> str:
        return self._codec_name

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height
