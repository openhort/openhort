"""Intent system — Android-like URI handlers for content routing.

Plugins register intent handlers for URI schemes (photo, geo, file, text, etc.).
When a phone sends a photo or GPS coordinate, the system routes it to the
matching plugin(s).

Built-in URI schemes:

- ``photo`` — JPEG/PNG image bytes + metadata
- ``geo`` — latitude, longitude, altitude, accuracy
- ``file`` — binary file + filename + mime type
- ``text`` — plain text string
- ``url`` — URL string
- ``contact`` — vCard data
- ``scan`` — barcode/QR code content
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IntentHandler:
    """Declaration of an intent this plugin can handle."""

    uri_scheme: str  # e.g. "photo", "geo", "file", "text"
    mime_types: list[str] = field(default_factory=lambda: ["*/*"])
    description: str = ""
    method: str = ""  # method name on the plugin instance


@dataclass(frozen=True)
class IntentData:
    """Payload delivered to an intent handler."""

    scheme: str
    mime_type: str = ""
    data: bytes = b""  # binary payload (photo, file)
    text: str = ""  # text payload (text, url, scan)
    metadata: dict[str, Any] = field(default_factory=dict)  # extra info (lat, lon, filename, etc.)


class IntentMixin:
    """Mixin for plugins that handle intents.

    Example::

        class MyPlugin(PluginBase, IntentMixin):
            def get_intent_handlers(self) -> list[IntentHandler]:
                return [
                    IntentHandler(
                        uri_scheme="photo",
                        mime_types=["image/jpeg", "image/png"],
                        description="Detect faces in photo",
                        method="handle_photo",
                    ),
                ]

            async def handle_photo(self, intent: IntentData) -> dict:
                faces = self.detect_faces(intent.data)
                return {"faces_found": len(faces)}
    """

    def get_intent_handlers(self) -> list[IntentHandler]:
        """Return intent handlers this plugin provides."""
        return []
