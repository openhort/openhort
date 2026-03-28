"""Tests for hort.peer2peer.video_track and webm_stream."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from PIL import Image

from hort.peer2peer.video_track import (
    ScreenCaptureTrack,
    ScreenCaptureProvider,
    WebMEncoder,
)


class TestScreenCaptureTrack:
    @pytest.mark.asyncio
    async def test_test_pattern(self) -> None:
        """Track produces frames even without a capture function."""
        track = ScreenCaptureTrack(fps=10)
        frame = await track.recv()
        assert frame is not None
        assert frame.width > 0
        assert frame.height > 0
        track.stop()

    @pytest.mark.asyncio
    async def test_multiple_frames(self) -> None:
        """Track produces multiple sequential frames."""
        track = ScreenCaptureTrack(fps=30)
        frames = []
        for _ in range(3):
            frames.append(await track.recv())
        assert len(frames) == 3
        # Timestamps should increase
        assert frames[1].pts > frames[0].pts
        assert frames[2].pts > frames[1].pts
        track.stop()

    @pytest.mark.asyncio
    async def test_with_capture_function(self) -> None:
        """Track uses the capture function when set."""
        img = Image.new("RGB", (640, 480), color=(100, 150, 200))

        def fake_capture(window_id: int, max_width: int) -> Image.Image:
            return img.copy()

        track = ScreenCaptureTrack(fps=10)
        track.set_capture_function(fake_capture)
        track.set_window(101)

        frame = await track.recv()
        assert frame.width == 640
        assert frame.height == 480
        track.stop()

    @pytest.mark.asyncio
    async def test_capture_failure_fallback(self) -> None:
        """Track falls back to test pattern on capture failure."""
        def failing_capture(window_id: int, max_width: int) -> None:
            return None

        track = ScreenCaptureTrack(fps=10)
        track.set_capture_function(failing_capture)
        track.set_window(101)

        frame = await track.recv()
        assert frame is not None  # test pattern
        track.stop()

    def test_fps_property(self) -> None:
        track = ScreenCaptureTrack(fps=15)
        assert track.fps == 15
        track.fps = 30
        assert track.fps == 30
        track.fps = 0
        assert track.fps == 1  # clamped to min
        track.fps = 100
        assert track.fps == 60  # clamped to max

    def test_set_window(self) -> None:
        track = ScreenCaptureTrack()
        track.set_window(42)
        assert track._window_id == 42


class TestWebMEncoder:
    def test_create_vp8(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=640, height=480)
        assert encoder.codec == "vp8"
        assert encoder.width == 640
        assert encoder.height == 480
        encoder.close()

    def test_create_vp9(self) -> None:
        encoder = WebMEncoder(codec="vp9", fps=15, width=640, height=480)
        assert encoder.codec == "vp9"
        encoder.close()

    def test_encode_frame_vp8(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        img = Image.new("RGB", (320, 240), color=(50, 100, 150))
        data = encoder.encode_frame(img)
        # VP8 may buffer first frame, data could be empty or contain bytes
        assert isinstance(data, bytes)
        encoder.close()

    def test_encode_frame_vp9(self) -> None:
        encoder = WebMEncoder(codec="vp9", fps=15, width=320, height=240)
        img = Image.new("RGB", (320, 240), color=(50, 100, 150))
        data = encoder.encode_frame(img)
        assert isinstance(data, bytes)
        encoder.close()

    def test_encode_multiple_frames(self) -> None:
        """After a few frames, encoder should produce output."""
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        total_bytes = 0
        for i in range(10):
            img = Image.new("RGB", (320, 240), color=(i * 25, 100, 150))
            data = encoder.encode_frame(img)
            total_bytes += len(data)
        assert total_bytes > 0  # at least some frames produced output
        encoder.close()

    def test_encode_resizes(self) -> None:
        """Encoder resizes input that doesn't match configured dimensions."""
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
        # Should start with EBML header (WebM magic bytes)
        assert init[:4] == b'\x1a\x45\xdf\xa3'
        encoder.close()

    def test_init_segment_cached(self) -> None:
        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        init1 = encoder.get_init_segment()
        init2 = encoder.get_init_segment()
        assert init1 is init2  # same object (cached)
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
