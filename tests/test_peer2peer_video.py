"""Tests for hort.peer2peer.video_track and webm_stream."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from PIL import Image

from hort.peer2peer.video_track import (
    ScreenCaptureTrack,
    ScreenCaptureProvider,
    ViewportConfig,
    WebMEncoder,
)


class TestViewportConfig:
    def test_defaults(self) -> None:
        vp = ViewportConfig()
        assert vp.x == 0.0
        assert vp.y == 0.0
        assert vp.w == 1.0
        assert vp.h == 1.0
        assert vp.client_width == 1920
        assert vp.client_height == 1080

    def test_crop_box_full(self) -> None:
        """Full viewport = full image."""
        vp = ViewportConfig()
        box = vp.crop_box(5120, 1440)
        assert box == (0, 0, 5120, 1440)

    def test_crop_box_partial(self) -> None:
        """Partial viewport crops correctly."""
        vp = ViewportConfig(x=0.25, y=0.25, w=0.5, h=0.5)
        box = vp.crop_box(1000, 1000)
        assert box == (250, 250, 750, 750)

    def test_crop_box_clamped(self) -> None:
        """Viewport extending past image is clamped."""
        vp = ViewportConfig(x=0.8, y=0.8, w=0.5, h=0.5)
        box = vp.crop_box(100, 100)
        left, top, right, bottom = box
        assert right <= 100
        assert bottom <= 100
        assert right > left
        assert bottom > top

    def test_crop_box_even_dimensions(self) -> None:
        """Output dimensions are always even (VP8/VP9 requirement)."""
        vp = ViewportConfig(x=0.0, y=0.0, w=0.333, h=0.333)
        box = vp.crop_box(101, 101)
        w = box[2] - box[0]
        h = box[3] - box[1]
        assert w % 2 == 0
        assert h % 2 == 0

    def test_output_size_even(self) -> None:
        vp = ViewportConfig(client_width=1921, client_height=1081)
        w, h = vp.output_size()
        assert w % 2 == 0
        assert h % 2 == 0
        assert w == 1920
        assert h == 1080


class TestScreenCaptureTrack:
    @pytest.mark.asyncio
    async def test_test_pattern(self) -> None:
        track = ScreenCaptureTrack(fps=10)
        frame = await track.recv()
        assert frame is not None
        assert frame.width > 0
        assert frame.height > 0
        track.stop()

    @pytest.mark.asyncio
    async def test_multiple_frames(self) -> None:
        track = ScreenCaptureTrack(fps=30)
        frames = []
        for _ in range(3):
            frames.append(await track.recv())
        assert len(frames) == 3
        assert frames[1].pts > frames[0].pts
        track.stop()

    @pytest.mark.asyncio
    async def test_with_capture_function(self) -> None:
        img = Image.new("RGB", (640, 480), color=(100, 150, 200))

        def fake_capture(window_id: int, max_width: int) -> Image.Image:
            return img.copy()

        track = ScreenCaptureTrack(fps=10)
        track.set_capture_function(fake_capture)
        track.set_window(101)

        frame = await track.recv()
        # Output should match client resolution (default 1920x1080)
        # since capture is 640x480 and viewport is full
        assert frame.width > 0
        assert frame.height > 0
        track.stop()

    @pytest.mark.asyncio
    async def test_viewport_crop(self) -> None:
        """Viewport crops the capture to the visible region."""
        img = Image.new("RGB", (1000, 1000), color=(100, 100, 100))
        # Draw a red square in the top-left quarter
        for x in range(500):
            for y in range(500):
                img.putpixel((x, y), (255, 0, 0))

        def fake_capture(window_id: int, max_width: int) -> Image.Image:
            return img.copy()

        track = ScreenCaptureTrack(fps=10)
        track.set_capture_function(fake_capture)
        track.set_window(101)
        # Set viewport to top-left quarter
        track.update_viewport({
            "viewport_x": 0.0, "viewport_y": 0.0,
            "viewport_w": 0.5, "viewport_h": 0.5,
            "client_width": 500, "client_height": 500,
        })

        frame = await track.recv()
        assert frame.width == 500
        assert frame.height == 500
        track.stop()

    @pytest.mark.asyncio
    async def test_capture_failure_fallback(self) -> None:
        def failing_capture(window_id: int, max_width: int) -> None:
            return None

        track = ScreenCaptureTrack(fps=10)
        track.set_capture_function(failing_capture)
        track.set_window(101)

        frame = await track.recv()
        assert frame is not None
        track.stop()

    def test_fps_property(self) -> None:
        track = ScreenCaptureTrack(fps=15)
        assert track.fps == 15
        track.fps = 30
        assert track.fps == 30
        track.fps = 0
        assert track.fps == 1
        track.fps = 100
        assert track.fps == 60

    def test_set_window(self) -> None:
        track = ScreenCaptureTrack()
        track.set_window(42)
        assert track._window_id == 42

    def test_update_viewport(self) -> None:
        track = ScreenCaptureTrack()
        track.update_viewport({
            "viewport_x": 0.1, "viewport_y": 0.2,
            "viewport_w": 0.5, "viewport_h": 0.4,
            "client_width": 1080, "client_height": 720,
        })
        assert track.viewport.x == 0.1
        assert track.viewport.y == 0.2
        assert track.viewport.w == 0.5
        assert track.viewport.h == 0.4
        assert track.viewport.client_width == 1080

    def test_update_viewport_zoom(self) -> None:
        """Zoom recalculates viewport size."""
        track = ScreenCaptureTrack()
        track.update_viewport({"zoom": 2.0})
        assert track.viewport.zoom == 2.0
        assert track.viewport.w == 0.5  # 1/zoom
        assert track.viewport.h == 0.5


class TestWebMEncoder:
    def test_create_vp8(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=640, height=480)
        assert encoder.codec == "vp8"
        encoder.close()

    def test_create_vp9(self) -> None:
        encoder = WebMEncoder(codec="vp9", fps=15, width=640, height=480)
        assert encoder.codec == "vp9"
        encoder.close()

    def test_encode_frame_vp8(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        img = Image.new("RGB", (320, 240), color=(50, 100, 150))
        data = encoder.encode_frame(img)
        assert isinstance(data, bytes)
        encoder.close()

    def test_encode_frame_vp9(self) -> None:
        encoder = WebMEncoder(codec="vp9", fps=15, width=320, height=240)
        img = Image.new("RGB", (320, 240), color=(50, 100, 150))
        data = encoder.encode_frame(img)
        assert isinstance(data, bytes)
        encoder.close()

    def test_encode_multiple_frames(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        total_bytes = 0
        for i in range(10):
            img = Image.new("RGB", (320, 240), color=(i * 25, 100, 150))
            data = encoder.encode_frame(img)
            total_bytes += len(data)
        assert total_bytes > 0
        encoder.close()

    def test_encode_resizes(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        img = Image.new("RGB", (800, 600), color=(100, 100, 100))
        data = encoder.encode_frame(img)
        assert isinstance(data, bytes)
        encoder.close()

    def test_get_init_segment(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        init = encoder.get_init_segment()
        assert isinstance(init, bytes)
        assert len(init) > 0
        assert init[:4] == b'\x1a\x45\xdf\xa3'
        encoder.close()

    def test_init_segment_cached(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        init1 = encoder.get_init_segment()
        init2 = encoder.get_init_segment()
        assert init1 is init2
        encoder.close()


class TestScreenCaptureProvider:
    def test_no_provider(self) -> None:
        provider = ScreenCaptureProvider()
        result = provider.capture_pil(101, 800)
        assert result is None

    def test_set_provider(self) -> None:
        provider = ScreenCaptureProvider()
        mock = MagicMock()
        provider.set_provider(mock)
        assert provider._provider is mock
