"""WebM video streaming over WebSocket for proxy mode.

When the client connects via the HTTP proxy (not P2P), there's no WebRTC
video track. Instead, we encode screen captures as VP8 or VP9 in a WebM
container and stream the data over the existing binary WebSocket.

The browser uses Media Source Extensions (MSE) to decode and render
the stream in a <video> element — hardware accelerated, low latency.

Architecture:
    Server: capture → PIL Image → av VP8/VP9 encode → WebM packets → WebSocket
    Client: WebSocket → MSE SourceBuffer → <video> element → hardware decode

Usage::

    streamer = WebMStreamer(websocket, codec='vp8', fps=15)
    streamer.set_capture_function(capture_fn)
    streamer.set_window(window_id)
    await streamer.run()  # streams until disconnected
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any, Callable

import av

logger = logging.getLogger(__name__)


class WebMStreamer:
    """Streams VP8/VP9 encoded video over WebSocket as WebM segments.

    Each frame is captured, encoded, and sent as a binary WebSocket message.
    The first message is the WebM initialization segment (header).
    """

    def __init__(
        self,
        websocket: Any,
        codec: str = "vp8",
        fps: int = 15,
        max_width: int = 1920,
        bitrate: int = 2_000_000,
    ) -> None:
        self._ws = websocket
        self._codec = codec
        self._fps = fps
        self._max_width = max_width
        self._bitrate = bitrate
        self._window_id: int | None = None
        self._capture_fn: Callable[..., Any] | None = None
        self._running = False
        self._frame_count = 0

    def set_capture_function(self, fn: Callable[..., Any]) -> None:
        """Set fn(window_id, max_width) -> PIL.Image | None."""
        self._capture_fn = fn

    def set_window(self, window_id: int) -> None:
        self._window_id = window_id

    async def run(self) -> None:
        """Run the streaming loop until the WebSocket disconnects."""
        if not self._capture_fn or self._window_id is None:
            return

        self._running = True
        codec_lib = "libvpx" if self._codec == "vp8" else "libvpx-vp9"

        # First capture to get dimensions
        first_frame = await asyncio.get_event_loop().run_in_executor(
            None, self._capture_fn, self._window_id, self._max_width
        )
        if first_frame is None:
            return

        width = first_frame.width
        height = first_frame.height
        # Ensure even dimensions (required by VP8/VP9)
        width = width - (width % 2)
        height = height - (height % 2)

        logger.info("WebM stream starting: %s %dx%d @ %dfps", self._codec, width, height, self._fps)

        # Create encoder — write to a pipe-like buffer
        output_buf = io.BytesIO()
        container = av.open(output_buf, mode="w", format="webm", options={"live": "1"})
        stream = container.add_stream(codec_lib, rate=self._fps)
        stream.width = width
        stream.height = height
        stream.bit_rate = self._bitrate
        stream.pix_fmt = "yuv420p"

        if self._codec == "vp8":
            stream.options = {"cpu-used": "8", "deadline": "realtime", "lag-in-frames": "0"}
        else:
            stream.options = {"cpu-used": "8", "deadline": "realtime", "lag-in-frames": "0", "row-mt": "1"}

        # Send init segment (WebM header)
        container.mux()  # force header write
        init_data = output_buf.getvalue()
        if init_data:
            try:
                await self._ws.send_bytes(init_data)
            except Exception:
                self._running = False
                return

        start_time = time.monotonic()

        try:
            while self._running:
                target_time = start_time + (self._frame_count / self._fps)
                now = time.monotonic()
                if target_time > now:
                    await asyncio.sleep(target_time - now)

                # Capture
                pil_image = await asyncio.get_event_loop().run_in_executor(
                    None, self._capture_fn, self._window_id, self._max_width
                )
                if pil_image is None:
                    await asyncio.sleep(0.5)
                    continue

                if pil_image.mode != "RGB":
                    pil_image = pil_image.convert("RGB")

                # Resize to match encoder dimensions
                if pil_image.width != width or pil_image.height != height:
                    from PIL import Image
                    pil_image = pil_image.resize((width, height), Image.Resampling.LANCZOS)

                frame = av.VideoFrame.from_image(pil_image)
                frame.pts = self._frame_count
                pil_image.close()

                # Encode and send
                output_buf.seek(0)
                output_buf.truncate()

                for packet in stream.encode(frame):
                    container.mux(packet)

                data = output_buf.getvalue()
                if data:
                    try:
                        await self._ws.send_bytes(data)
                    except Exception:
                        break

                self._frame_count += 1

                if self._frame_count % 100 == 0:
                    elapsed = time.monotonic() - start_time
                    actual_fps = self._frame_count / elapsed if elapsed > 0 else 0
                    logger.info("WebM stream: %d frames, %.1f fps", self._frame_count, actual_fps)

        finally:
            # Flush encoder
            try:
                for packet in stream.encode():
                    container.mux(packet)
                container.close()
            except Exception:
                pass

            self._running = False
            logger.info("WebM stream ended after %d frames", self._frame_count)

    def stop(self) -> None:
        """Signal the streaming loop to stop."""
        self._running = False
