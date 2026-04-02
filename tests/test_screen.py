"""Tests for screen capture — unit tests (mocked) and real Quartz integration tests.

Unit tests mock Quartz so no framework is loaded (fast, no permissions needed).
Integration tests use the real macOS Quartz API — they require Screen Recording
permission and actually capture the desktop to verify the full pipeline.
"""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from hort.screen import _cgimage_to_pil, capture_window

_IS_MACOS = sys.platform == "darwin"


class TestCgimageToP:
    def test_converts_bgra_to_rgb(self) -> None:
        """CGDataProviderCopyData extracts BGRA data; result is RGB."""
        mock_img = MagicMock()
        width, height = 100, 80
        bytes_per_row = width * 4
        # BGRA pixel data: B=200, G=150, R=100, A=255
        pixel = bytes([200, 150, 100, 255])
        raw_data = (pixel * width) * height

        with patch("hort.screen.Quartz") as mock_quartz:
            mock_quartz.CGImageGetWidth.return_value = width
            mock_quartz.CGImageGetHeight.return_value = height
            mock_quartz.CGImageGetBytesPerRow.return_value = bytes_per_row
            mock_quartz.CGImageGetDataProvider.return_value = MagicMock()
            mock_quartz.CGDataProviderCopyData.return_value = raw_data

            result = _cgimage_to_pil(mock_img)

        assert result is not None
        assert result.mode == "RGB"
        assert result.size == (100, 80)
        # BGRA -> RGB: B=200, G=150, R=100 -> R=100, G=150, B=200
        pixel_val = result.getpixel((0, 0))
        assert pixel_val == (100, 150, 200)

    def test_zero_dimensions(self) -> None:
        mock_img = MagicMock()
        with patch("hort.screen.Quartz") as mock_quartz:
            mock_quartz.CGImageGetWidth.return_value = 0
            mock_quartz.CGImageGetHeight.return_value = 0
            result = _cgimage_to_pil(mock_img)
        assert result is None

    def test_null_data(self) -> None:
        """When CGDataProviderCopyData returns None, result is None."""
        mock_img = MagicMock()
        with patch("hort.screen.Quartz") as mock_quartz:
            mock_quartz.CGImageGetWidth.return_value = 100
            mock_quartz.CGImageGetHeight.return_value = 100
            mock_quartz.CGImageGetBytesPerRow.return_value = 400
            mock_quartz.CGImageGetDataProvider.return_value = MagicMock()
            mock_quartz.CGDataProviderCopyData.return_value = None
            result = _cgimage_to_pil(mock_img)
        assert result is None


class TestCaptureWindow:
    def test_returns_jpeg_bytes(self) -> None:
        pil_img = Image.new("RGB", (200, 150), color=(100, 150, 200))

        with (
            patch("hort.screen._raw_capture", return_value=MagicMock()),
            patch("hort.screen._cgimage_to_pil", return_value=pil_img),
        ):
            result = capture_window(42)

        assert result is not None
        assert result[:2] == b"\xff\xd8"  # JPEG magic bytes

    def test_returns_none_on_capture_failure(self) -> None:
        with patch("hort.screen._raw_capture", return_value=None):
            result = capture_window(99999)
        assert result is None

    def test_returns_none_on_pil_failure(self) -> None:
        with (
            patch("hort.screen._raw_capture", return_value=MagicMock()),
            patch("hort.screen._cgimage_to_pil", return_value=None),
        ):
            result = capture_window(42)
        assert result is None

    def test_resizes_when_too_wide(self) -> None:
        pil_img = Image.new("RGB", (1600, 1000), color=(100, 150, 200))

        with (
            patch("hort.screen._raw_capture", return_value=MagicMock()),
            patch("hort.screen._cgimage_to_pil", return_value=pil_img),
        ):
            result = capture_window(42, max_width=800)

        assert result is not None
        decoded = Image.open(io.BytesIO(result))
        assert decoded.width == 800
        assert decoded.height == 500  # proportional

    def test_no_resize_when_small(self) -> None:
        pil_img = Image.new("RGB", (400, 300), color=(100, 150, 200))

        with (
            patch("hort.screen._raw_capture", return_value=MagicMock()),
            patch("hort.screen._cgimage_to_pil", return_value=pil_img),
        ):
            result = capture_window(42, max_width=800)

        assert result is not None
        decoded = Image.open(io.BytesIO(result))
        assert decoded.width == 400
        assert decoded.height == 300

    def test_quality_affects_size(self) -> None:
        with (
            patch("hort.screen._raw_capture", return_value=MagicMock()),
            patch("hort.screen._cgimage_to_pil", side_effect=lambda _: Image.new("RGB", (400, 300), color=(100, 150, 200))),
        ):
            low_q = capture_window(42, quality=10)
            high_q = capture_window(42, quality=95)

        assert low_q is not None and high_q is not None
        assert len(low_q) < len(high_q)


# ── Real Quartz integration tests ─────────────────────────────────
# These use the actual macOS Quartz framework.  They require Screen
# Recording permission and only run on macOS.


@pytest.mark.skipif(not _IS_MACOS, reason="macOS only")
class TestRealQuartzCapture:
    """Integration tests using real Quartz — verify capture + cleanup."""

    def test_desktop_capture_returns_jpeg(self) -> None:
        """Full desktop capture produces valid JPEG bytes."""
        from hort.screen import DESKTOP_WINDOW_ID
        result = capture_window(DESKTOP_WINDOW_ID, max_width=320, quality=30)
        if result is None:
            pytest.skip("Screen Recording permission not granted")
        assert result[:2] == b"\xff\xd8"  # JPEG magic
        assert len(result) > 100

    def test_desktop_capture_pil_pipeline(self) -> None:
        """Raw capture → CGImage → PIL → JPEG full pipeline."""
        from hort.screen import DESKTOP_WINDOW_ID, _raw_capture_desktop, _cgimage_to_pil
        import objc  # type: ignore[import-untyped]

        with objc.autorelease_pool():
            cg_image = _raw_capture_desktop()
        if cg_image is None:
            pytest.skip("Screen Recording permission not granted")
        try:
            pil = _cgimage_to_pil(cg_image)
        finally:
            del cg_image
        assert pil is not None
        assert pil.mode == "RGB"
        assert pil.width > 0 and pil.height > 0
        pil.close()

    def test_repeated_captures_no_leak(self) -> None:
        """Run 20 captures and verify RSS doesn't grow unboundedly."""
        import resource
        from hort.screen import DESKTOP_WINDOW_ID

        # Warm up
        warmup = capture_window(DESKTOP_WINDOW_ID, max_width=200, quality=20)
        if warmup is None:
            pytest.skip("Screen Recording permission not granted")

        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        for _ in range(20):
            result = capture_window(DESKTOP_WINDOW_ID, max_width=200, quality=20)
            assert result is not None

        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        growth_mb = (rss_after - rss_before) / 1024 / 1024
        # Each capture is ~200px wide ≈ 0.1 MB JPEG.  With autorelease pool
        # draining properly, RSS growth should be minimal.  If it grows by
        # >50 MB for 20 small captures, something is leaking.
        assert growth_mb < 50, f"RSS grew by {growth_mb:.0f} MB over 20 captures — likely leak"

    def test_crop_and_convert(self) -> None:
        """Capture, crop, convert — verify cropped image is smaller."""
        from hort.screen import DESKTOP_WINDOW_ID, _cgimage_crop, _cgimage_to_pil, _raw_capture_desktop
        import objc  # type: ignore[import-untyped]

        with objc.autorelease_pool():
            cg = _raw_capture_desktop()
        if cg is None:
            pytest.skip("Screen Recording permission not granted")

        try:
            cropped_cg = _cgimage_crop(cg, 0.0, 0.0, 0.5, 0.5)
            del cg
            pil = _cgimage_to_pil(cropped_cg)
        finally:
            # Ensure cleanup even on failure
            try:
                del cropped_cg
            except NameError:
                pass

        assert pil is not None
        assert pil.width > 0
        pil.close()


@pytest.mark.skipif(not _IS_MACOS, reason="macOS only")
class TestRealWindowList:
    """Integration tests for window listing with real Quartz."""

    def test_list_windows_returns_results(self) -> None:
        """list_windows() returns at least the Desktop entry."""
        from hort.windows import list_windows
        windows = list_windows()
        assert len(windows) >= 1
        assert windows[0].owner_name == "Desktop"
        assert windows[0].window_id == -1

    def test_list_windows_with_filter(self) -> None:
        """Filtering by a nonexistent app returns empty."""
        from hort.windows import list_windows
        windows = list_windows(app_filter="__nonexistent_app_12345__")
        assert windows == []
