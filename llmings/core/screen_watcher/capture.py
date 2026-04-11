"""Screen capture utilities for the watcher — region cropping and change detection."""

from __future__ import annotations

import hashlib
import io

from PIL import Image

from llmings.core.screen_watcher.models import RegionConfig, resolve_region


def crop_region(jpeg_bytes: bytes, region: RegionConfig) -> bytes:
    """Crop a JPEG image to a region defined by fractional coordinates.

    Returns JPEG bytes of the cropped area.
    """
    x, y, w, h = resolve_region(region)
    if (x, y, w, h) == (0.0, 0.0, 1.0, 1.0):
        return jpeg_bytes  # full — no crop needed

    img = Image.open(io.BytesIO(jpeg_bytes))
    iw, ih = img.size
    left = int(x * iw)
    top = int(y * ih)
    right = int((x + w) * iw)
    bottom = int((y + h) * ih)
    cropped = img.crop((left, top, right, bottom))

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def frame_hash(jpeg_bytes: bytes) -> str:
    """Compute a fast hash of JPEG bytes for change detection."""
    return hashlib.sha256(jpeg_bytes).hexdigest()


def frames_differ(hash_a: str | None, hash_b: str | None) -> bool:
    """Check if two frame hashes differ (i.e., visual change detected)."""
    if hash_a is None or hash_b is None:
        return True  # first frame is always "changed"
    return hash_a != hash_b
