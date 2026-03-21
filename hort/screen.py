"""Window screenshot capture via macOS Quartz API."""

from __future__ import annotations

import io

from PIL import Image

import Quartz  # type: ignore[import-untyped]


def _raw_capture(window_id: int) -> object | None:  # pragma: no cover
    """Capture a raw CGImage for the given window. Isolated for testability."""
    cg_image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        (
            Quartz.kCGWindowImageBoundsIgnoreFraming
            | Quartz.kCGWindowImageNominalResolution
        ),
    )
    result: object | None = cg_image
    return result


def _cgimage_to_pil(cg_image: object) -> Image.Image | None:
    """Convert a CGImage to a PIL Image."""
    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    if width == 0 or height == 0:
        return None

    bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)
    data_provider = Quartz.CGImageGetDataProvider(cg_image)
    raw_data = Quartz.CGDataProviderCopyData(data_provider)

    if raw_data is None:
        return None

    pil_image = Image.frombytes(
        "RGBA",
        (width, height),
        bytes(raw_data),
        "raw",
        "BGRA",
        bytes_per_row,
        1,
    )
    return pil_image.convert("RGB")


def capture_window(
    window_id: int,
    max_width: int = 800,
    quality: int = 70,
) -> bytes | None:
    """Capture a window screenshot as JPEG bytes.

    Args:
        window_id: The macOS window ID to capture.
        max_width: Maximum width in pixels (resized proportionally).
        quality: JPEG quality (1-100).

    Returns:
        JPEG bytes, or None if capture failed.
    """
    cg_image = _raw_capture(window_id)
    if cg_image is None:
        return None

    pil_image = _cgimage_to_pil(cg_image)
    if pil_image is None:
        return None

    if pil_image.width > max_width:
        ratio = max_width / pil_image.width
        new_height = int(pil_image.height * ratio)
        pil_image = pil_image.resize(
            (max_width, new_height), Image.Resampling.LANCZOS
        )

    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
