"""Window screenshot capture via macOS Quartz API.

MEMORY SAFETY: CGImage objects from ``CGWindowListCreateImage`` hold
native pixel buffers (tens of MB each). Python's GC doesn't track
these — they're Core Foundation objects. We explicitly release them
via ``del`` after extracting the pixel data to prevent unbounded
native memory growth during continuous streaming.

Key technique: crop with ``CGImageCreateWithImageInRect`` BEFORE
extracting pixel data so we never materialise the full Retina buffer
(~50 MB) into Python bytes.

All Quartz/objc imports are deferred to first use so that importing
this module does NOT load the frameworks.
"""

from __future__ import annotations

import importlib
import io
import types
from typing import Any

from PIL import Image


class _LazyModule:
    """Proxy that defers ``import <name>`` until first attribute access."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._mod: types.ModuleType | None = None

    def _ensure(self) -> types.ModuleType:
        if self._mod is None:
            self._mod = importlib.import_module(self._name)
        return self._mod

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._ensure(), attr)


# Module-level name so ``patch("hort.screen.Quartz")`` still works,
# but the framework only loads on first attribute access.
Quartz: Any = _LazyModule("Quartz")  # type: ignore[assignment]


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

    Uses ``CGDataProviderCopyData`` to extract pixel data.  The returned
    CFData is autoreleased, so the **caller** MUST wrap capture +
    conversion in ``objc.autorelease_pool()`` to drain it immediately.
    Without a pool, the data leaks on background threads.

    The earlier ``CGBitmapContextCreate`` approach avoided autorelease
    objects but leaked ~34 MB/frame from an internal CoreGraphics
    decompression cache that pyobjc couldn't release.
    ``CGDataProviderCopyData`` inside a pool leaks <2 MB/frame.
    """
    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    if width == 0 or height == 0:
        return None

    bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)
    provider = Quartz.CGImageGetDataProvider(cg_image)
    data = Quartz.CGDataProviderCopyData(provider)
    if data is None:
        return None

    pil_image = Image.frombuffer(
        "RGBA", (width, height), data, "raw", "BGRA", bytes_per_row, 1,
    )
    del data
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

    Wraps the capture in an ``objc.autorelease_pool()`` so that any
    autoreleased CF objects created by Quartz are drained immediately
    instead of leaking on background threads.

    Args:
        window_id: The macOS window ID, or ``DESKTOP_WINDOW_ID`` (-1)
            for full-screen capture.
        max_width: Maximum width in pixels (resized proportionally).
        quality: JPEG quality (1-100).

    Returns:
        JPEG bytes, or None if capture failed.
    """
    import objc  # type: ignore[import-untyped]

    with objc.autorelease_pool():
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
