"""Window screenshot capture via macOS Quartz API.

MEMORY SAFETY: CGImage objects from ``CGWindowListCreateImage`` hold
native pixel buffers (tens of MB each). Python's GC doesn't track
these — they're Core Foundation objects. We explicitly release them
via ``del`` after extracting the pixel data to prevent unbounded
native memory growth during continuous streaming.

Key technique: crop with ``CGImageCreateWithImageInRect`` BEFORE
extracting pixel data so we never materialise the full Retina buffer
(~50 MB) into Python bytes.
"""

from __future__ import annotations

import io

import objc  # type: ignore[import-untyped]
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
    """Convert a CGImage to a PIL RGB Image.

    Uses CGBitmapContext to render the image directly into a Python
    bytearray in RGBA order, avoiding CGDataProviderCopyData which
    creates autoreleased CF objects that leak on background threads.
    """
    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    if width == 0 or height == 0:
        return None

    # Render into a Python-owned buffer via CGBitmapContext.
    # This avoids CGDataProviderCopyData and its autoreleased CFData.
    bytes_per_row = width * 4
    buf = bytearray(bytes_per_row * height)
    colorspace = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        buf, width, height, 8, bytes_per_row, colorspace,
        Quartz.kCGImageAlphaPremultipliedLast,  # RGBA byte order
    )
    del colorspace
    if ctx is None:
        return None

    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, width, height), cg_image)
    del ctx  # flush and release context

    pil_image = Image.frombuffer("RGBA", (width, height), bytes(buf), "raw", "RGBA", bytes_per_row, 1)
    del buf
    rgb_image = pil_image.convert("RGB")
    pil_image.close()
    return rgb_image


def _cgimage_crop(cg_image: object, x: float, y: float, w: float, h: float) -> object:
    """Crop a CGImage using normalized coordinates (0-1).

    Uses CGImageCreateWithImageInRect to crop at the native level BEFORE
    pixel data extraction — avoids materialising the full buffer in Python.
    Returns the cropped CGImage (caller must del it).
    """
    img_w = Quartz.CGImageGetWidth(cg_image)
    img_h = Quartz.CGImageGetHeight(cg_image)
    rect = Quartz.CGRectMake(
        int(x * img_w),
        int(y * img_h),
        int(w * img_w),
        int(h * img_h),
    )
    cropped = Quartz.CGImageCreateWithImageInRect(cg_image, rect)
    return cropped


def _encode_pil_to_jpeg(
    pil_image: Image.Image,
    max_width: int,
    quality: int,
) -> bytes:
    """Resize (if needed) and encode a PIL image to JPEG bytes."""
    if pil_image.width > max_width:
        ratio = max_width / pil_image.width
        new_height = int(pil_image.height * ratio)
        new_img = pil_image.resize(
            (max_width, new_height), Image.Resampling.LANCZOS,
        )
        pil_image.close()
        pil_image = new_img

    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=quality)
    pil_image.close()
    result = buf.getvalue()
    buf.close()
    return result


# Magic window_id that means "capture the whole desktop"
DESKTOP_WINDOW_ID = -1


def _raw_capture_desktop() -> object | None:  # pragma: no cover
    """Capture the main display's desktop (all windows composited) as a CGImage.

    Uses CGDisplayCreateImage for the main display only (not all monitors),
    so coordinates map 1:1 with CGDisplay pixel dimensions.
    """
    cg_image = Quartz.CGDisplayCreateImage(Quartz.CGMainDisplayID())
    result: object | None = cg_image
    return result


def capture_window(
    window_id: int,
    max_width: int = 800,
    quality: int = 70,
) -> bytes | None:
    """Capture a window (or the full desktop) as JPEG bytes.

    Args:
        window_id: The macOS window ID, or ``DESKTOP_WINDOW_ID`` (-1)
            for full-screen capture.
        max_width: Maximum width in pixels (resized proportionally).
        quality: JPEG quality (1-100).

    Returns:
        JPEG bytes, or None if capture failed.
    """
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

    return _encode_pil_to_jpeg(pil_image, max_width, quality)
