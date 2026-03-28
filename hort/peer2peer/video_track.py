"""Video stream track for WebRTC — viewport-aware screen capture with VP8/VP9.

Implements an aiortc VideoStreamTrack that captures the screen with two modes:
- **Viewport stream** (high FPS): captures only the visible region at the
  client's native resolution. This is what the user sees.
- **Thumbnail stream** (low FPS): captures the full screen at low resolution
  for the navigator overview.

The client reports its viewport (position, zoom, device resolution) and the
server crops and scales the capture accordingly. When the user pans/zooms,
only the viewport coordinates change — no full-screen re-encode.

Architecture:
    Full screen (5120x1440)
    ┌─────────────────────────────────────┐
    │                                     │
    │    ┌──────────┐                     │
    │    │ Viewport │ ← high-res, 30fps  │
    │    │ 1920x1080│   (client native)   │
    │    └──────────┘                     │
    │                                     │
    │    thumbnail: 640px wide, 0.3fps    │
    └─────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import fractions
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import av
from aiortc import VideoStreamTrack

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


@dataclass
class ViewportConfig:
    """Client's viewport state — what region of the screen is visible."""

    # Viewport position as fraction of full screen (0.0-1.0)
    x: float = 0.0
    y: float = 0.0
    # Viewport size as fraction of full screen (0.0-1.0, 1.0 = full screen)
    w: float = 1.0
    h: float = 1.0
    # Client device resolution (output size)
    client_width: int = 1920
    client_height: int = 1080
    # Zoom level (1.0 = fit full screen, 2.0 = 2x zoom, etc.)
    zoom: float = 1.0

    def crop_box(self, src_width: int, src_height: int) -> tuple[int, int, int, int]:
        """Calculate the pixel crop box for the source image.

        Returns (left, top, right, bottom) in source pixels.
        """
        left = int(self.x * src_width)
        top = int(self.y * src_height)
        right = int((self.x + self.w) * src_width)
        bottom = int((self.y + self.h) * src_height)
        # Clamp to source bounds
        left = max(0, min(left, src_width))
        top = max(0, min(top, src_height))
        right = max(left + 2, min(right, src_width))  # min 2px wide
        bottom = max(top + 2, min(bottom, src_height))
        # Ensure even dimensions (VP8/VP9 requirement)
        right = left + ((right - left) // 2) * 2
        bottom = top + ((bottom - top) // 2) * 2
        return left, top, right, bottom

    def output_size(self) -> tuple[int, int]:
        """Output dimensions, ensuring even values."""
        w = max(2, self.client_width - (self.client_width % 2))
        h = max(2, self.client_height - (self.client_height % 2))
        return w, h


class ScreenCaptureTrack(VideoStreamTrack):
    """VideoStreamTrack with viewport-aware capture.

    Captures the full screen, crops to the viewport region, and resizes
    to the client's device resolution. The viewport is updated dynamically
    by the client via video_config messages.
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
        self._capture_fn: Any = None
        self._frame_count = 0
        self._start_time: float | None = None
        self._last_frame_time: float = 0.0
        self._last_capture_ms = 0.0
        self.viewport = ViewportConfig()

    def set_capture_function(self, fn: Any) -> None:
        """Set fn(window_id, max_width) -> PIL.Image | None."""
        self._capture_fn = fn

    def set_window(self, window_id: int) -> None:
        self._window_id = window_id

    def update_viewport(self, config: dict[str, Any]) -> None:
        """Update viewport from a video_config message."""
        if "viewport_x" in config:
            self.viewport.x = float(config["viewport_x"])
        if "viewport_y" in config:
            self.viewport.y = float(config["viewport_y"])
        if "viewport_w" in config:
            self.viewport.w = float(config["viewport_w"])
        if "viewport_h" in config:
            self.viewport.h = float(config["viewport_h"])
        if "client_width" in config:
            self.viewport.client_width = int(config["client_width"])
        if "client_height" in config:
            self.viewport.client_height = int(config["client_height"])
        if "zoom" in config:
            self.viewport.zoom = float(config["zoom"])
            # Recalculate viewport size from zoom
            self.viewport.w = min(1.0, 1.0 / self.viewport.zoom)
            self.viewport.h = min(1.0, 1.0 / self.viewport.zoom)

    @property
    def fps(self) -> int:
        return self._fps

    @fps.setter
    def fps(self, value: int) -> None:
        self._fps = max(1, min(60, value))

    async def recv(self) -> av.VideoFrame:
        if self._start_time is None:
            self._start_time = time.time()

        # Capture first, then sleep for remaining frame budget
        t0 = time.time()
        frame = await self._capture_frame()

        # PTS based on wall clock (not frame count) to avoid drift
        elapsed = t0 - self._start_time
        frame.pts = int(elapsed * 90000)  # 90kHz clock
        frame.time_base = fractions.Fraction(1, 90000)

        # Sleep for remaining frame budget (if capture was fast enough)
        capture_time = time.time() - t0
        sleep_time = (1.0 / self._fps) - capture_time
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

        self._frame_count += 1
        return frame

    async def _capture_frame(self) -> av.VideoFrame:
        if self._capture_fn and self._window_id is not None:
            try:
                t0 = time.monotonic()
                # Capture at client viewport resolution — never more than needed.
                # This is the key optimization: a 5K screen captured at 1920px
                # takes ~20ms instead of ~80ms, and VP8 encodes 4x faster.
                out_w, _ = self.viewport.output_size()
                capture_width = min(out_w, self._max_width)
                pil_image = await asyncio.get_event_loop().run_in_executor(
                    None, self._capture_fn, self._window_id, capture_width
                )
                self._last_capture_ms = (time.monotonic() - t0) * 1000

                if self._frame_count % 100 == 0:
                    logger.info(
                        "video track: %d frames, capture %.0fms, %dx%d → %dx%d",
                        self._frame_count, self._last_capture_ms,
                        pil_image.width if pil_image else 0,
                        pil_image.height if pil_image else 0,
                        *self.viewport.output_size(),
                    )

                if pil_image is not None:
                    if pil_image.mode != "RGB":
                        pil_image = pil_image.convert("RGB")

                    # Crop to viewport region
                    src_w, src_h = pil_image.size
                    crop_box = self.viewport.crop_box(src_w, src_h)
                    cropped = pil_image.crop(crop_box)
                    pil_image.close()

                    # Resize to client device resolution
                    out_w, out_h = self.viewport.output_size()
                    if cropped.size != (out_w, out_h):
                        from PIL import Image as _Image
                        resized = cropped.resize((out_w, out_h), _Image.Resampling.LANCZOS)
                        cropped.close()
                        cropped = resized

                    frame = av.VideoFrame.from_image(cropped)
                    cropped.close()
                    return frame
            except Exception as exc:
                if self._frame_count % 100 == 0:
                    logger.debug("capture error: %s", exc)

        return self._test_pattern()

    def _test_pattern(self) -> av.VideoFrame:
        from PIL import Image, ImageDraw

        out_w, out_h = self.viewport.output_size()
        img = Image.new("RGB", (out_w, out_h), color=(26, 26, 46))
        draw = ImageDraw.Draw(img)
        bar_x = int((self._frame_count * 5) % out_w)
        draw.rectangle([bar_x, 0, bar_x + 4, out_h], fill=(124, 77, 255))
        cx, cy = out_w // 2, out_h // 2
        draw.rectangle([cx - 60, cy - 20, cx + 60, cy + 20], fill=(22, 33, 62))
        frame = av.VideoFrame.from_image(img)
        img.close()
        return frame


class ScreenCaptureProvider:
    """Provides screen capture as PIL Images for the video track."""

    def __init__(self) -> None:
        self._provider: Any = None

    def set_provider(self, provider: Any) -> None:
        self._provider = provider

    def capture_pil(self, window_id: int, max_width: int) -> Any:
        """Capture a window and return as PIL Image."""
        if not self._provider:
            return None

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

            # Only resize if max_width is a real limit (not 99999)
            if max_width < 9999 and pil_image.width > max_width:
                ratio = max_width / pil_image.width
                new_height = int(pil_image.height * ratio)
                from PIL import Image
                resized = pil_image.resize((max_width, new_height), Image.Resampling.LANCZOS)
                pil_image.close()
                return resized

            return pil_image
        except ImportError:
            return None


class WebMEncoder:
    """Encodes video frames to VP8 or VP9 WebM for the proxy/WebSocket path."""

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
        import io

        self._output = io.BytesIO()

        codec_lib = "libvpx" if self._codec_name == "vp8" else "libvpx-vp9"

        self._container = av.open(self._output, mode="w", format="webm")
        self._stream = self._container.add_stream(codec_lib, rate=self._fps)
        self._stream.width = self._width
        self._stream.height = self._height
        self._stream.bit_rate = self._bitrate
        self._stream.pix_fmt = "yuv420p"

        if self._codec_name == "vp8":
            self._stream.options = {
                "cpu-used": "8",
                "deadline": "realtime",
                "lag-in-frames": "0",
            }
        else:
            self._stream.options = {
                "cpu-used": "8",
                "deadline": "realtime",
                "lag-in-frames": "0",
                "row-mt": "1",
            }

    def encode_frame(self, pil_image: Any) -> bytes:
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        if pil_image.width != self._width or pil_image.height != self._height:
            from PIL import Image
            pil_image = pil_image.resize(
                (self._width, self._height), Image.Resampling.LANCZOS
            )

        frame = av.VideoFrame.from_image(pil_image)
        frame.pts = self._frame_count
        self._frame_count += 1

        self._output.seek(0)
        self._output.truncate()

        for packet in self._stream.encode(frame):
            self._container.mux(packet)

        return self._output.getvalue()

    def get_init_segment(self) -> bytes:
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
        if self._container:
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
