"""Tests for screen capture."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image

from hort.screen import _cgimage_to_pil, capture_window


def _make_mock_cgimage(width: int, height: int) -> MagicMock:
    """Create a mock CGImage with BGRA pixel data."""
    mock_image = MagicMock()
    bytes_per_row = width * 4
    # Create BGRA pixel data (blue, green, red, alpha)
    pixel = bytes([200, 150, 100, 255])  # BGRA
    row = pixel * width
    padding = bytes(bytes_per_row - len(row))
    raw_data = (row + padding) * height

    return mock_image, width, height, bytes_per_row, raw_data


class TestCgimageToP:
    def test_converts_bgra_to_rgb(self) -> None:
        _, width, height, bpr, raw_data = _make_mock_cgimage(100, 80)
        mock_img = MagicMock()

        with (
            patch("hort.screen.Quartz") as mock_quartz,
        ):
            mock_quartz.CGImageGetWidth.return_value = width
            mock_quartz.CGImageGetHeight.return_value = height
            mock_quartz.CGImageGetBytesPerRow.return_value = bpr
            mock_quartz.CGImageGetDataProvider.return_value = MagicMock()
            mock_quartz.CGDataProviderCopyData.return_value = raw_data

            result = _cgimage_to_pil(mock_img)

        assert result is not None
        assert result.mode == "RGB"
        assert result.size == (100, 80)
        # Verify BGRA -> RGB conversion: B=200, G=150, R=100 -> R=100, G=150, B=200
        pixel = result.getpixel((0, 0))
        assert pixel == (100, 150, 200)

    def test_zero_dimensions(self) -> None:
        mock_img = MagicMock()
        with patch("hort.screen.Quartz") as mock_quartz:
            mock_quartz.CGImageGetWidth.return_value = 0
            mock_quartz.CGImageGetHeight.return_value = 0
            result = _cgimage_to_pil(mock_img)
        assert result is None

    def test_null_data(self) -> None:
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
        pil_img = Image.new("RGB", (400, 300), color=(100, 150, 200))

        with (
            patch("hort.screen._raw_capture", return_value=MagicMock()),
            patch("hort.screen._cgimage_to_pil", return_value=pil_img),
        ):
            low_q = capture_window(42, quality=10)
            high_q = capture_window(42, quality=95)

        assert low_q is not None and high_q is not None
        assert len(low_q) < len(high_q)
