"""Camera Scan plugin — processes images sent from phone camera.

Demonstrates the **client→server image flow**:
1. Phone browser accesses camera via getUserMedia() or file input
2. JS captures/selects an image and sends it as base64 to the server
3. Server decodes it, analyzes it (QR/barcode detection, size analysis)
4. Returns the result to the browser

The analysis runs on the server, not in the browser, so plugins
can use any Python library (Pillow, OpenCV, ML models, etc.).

For QR detection, we use PIL + simple dimension analysis as a
lightweight example. For production, add ``pyzbar`` or ``opencv-python``.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from typing import Any

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import Response

from hort.llming import LlmingBase, Power, PowerType


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine from sync context."""
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


class CameraScan(LlmingBase):
    """Receives images from the phone camera and processes them."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Camera scan plugin activated")

    def analyze_image(self, data: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
        """Analyze an image. Returns metadata + detection results.

        This is where you'd plug in real analysis:
        - pyzbar for QR/barcode detection
        - opencv for object detection
        - ML models for classification
        """
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        width, height = img.size
        mode = img.mode

        result: dict[str, Any] = {
            "width": width,
            "height": height,
            "mode": mode,
            "format": img.format or mime_type.split("/")[-1].upper(),
            "size_bytes": len(data),
            "aspect_ratio": round(width / height, 2) if height else 0,
        }

        # Color analysis (average color of center region)
        try:
            center = img.crop((width // 4, height // 4, 3 * width // 4, 3 * height // 4))
            if center.mode != "RGB":
                center = center.convert("RGB")
            pixels = list(center.getdata())
            n = len(pixels)
            if n > 0:
                avg_r = sum(p[0] for p in pixels) // n
                avg_g = sum(p[1] for p in pixels) // n
                avg_b = sum(p[2] for p in pixels) // n
                result["avg_color"] = f"#{avg_r:02x}{avg_g:02x}{avg_b:02x}"
                brightness = (avg_r * 299 + avg_g * 587 + avg_b * 114) // 1000
                result["brightness"] = brightness
                result["is_dark"] = brightness < 128
        except Exception:
            pass

        # Try QR detection via pyzbar if available
        try:
            from pyzbar.pyzbar import decode as qr_decode
            codes = qr_decode(img)
            if codes:
                result["qr_codes"] = [
                    {"data": c.data.decode("utf-8", errors="replace"), "type": c.type}
                    for c in codes
                ]
        except ImportError:
            result["qr_detection"] = "pyzbar not installed — install with: pip install pyzbar"

        return result

    # ===== FastAPI Router (receives images from browser) =====

    def get_router(self) -> APIRouter:
        router = APIRouter()
        plugin = self

        @router.post("/scan")
        async def scan_image(request: Request) -> Response:
            """Receive an image (base64 JSON) and analyze it.

            Expected body: {"image": "<base64>", "mime_type": "image/jpeg"}
            """
            import json

            body = await request.json()
            image_b64 = body.get("image", "")
            mime_type = body.get("mime_type", "image/jpeg")

            if not image_b64:
                return Response(
                    content=json.dumps({"error": "No image provided"}),
                    media_type="application/json", status_code=400,
                )

            # Decode base64
            data = base64.b64decode(image_b64)

            # Analyze
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, plugin.analyze_image, data, mime_type)

            # Optionally save the scan
            if plugin.config.get("features", {}).get("save_scans", True):
                ts = int(time.time())
                ext = "jpg" if "jpeg" in mime_type else "png"
                filename = f"scan_{ts}.{ext}"
                await plugin.files.save(filename, data, mime_type=mime_type, ttl_seconds=86400)
                result["saved_as"] = filename

            # Store scan result
            await plugin.store.put(f"scan:{int(time.time())}", result, ttl_seconds=86400)

            return Response(
                content=json.dumps(result, default=str),
                media_type="application/json",
            )

        @router.get("/scans")
        async def list_scans() -> Response:
            """List recent scan results."""
            import json
            keys = await plugin.store.list_keys("scan:")
            keys.sort(reverse=True)
            results = []
            for k in keys[:20]:
                entry = await plugin.store.get(k)
                if entry:
                    entry["key"] = k
                    results.append(entry)
            return Response(content=json.dumps(results, default=str), media_type="application/json")

        return router

    # ===== Intent handler (receives photos from phone share) =====

    async def handle_photo_intent(self, intent_data: Any) -> dict[str, Any]:
        """Handle a photo intent — same analysis as the /scan endpoint."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self.analyze_image, intent_data.data, intent_data.mime_type
        )
        if self.config.get("features", {}).get("save_scans", True):
            ts = int(time.time())
            ext = "jpg" if "jpeg" in intent_data.mime_type else "png"
            await self.files.save(f"intent_{ts}.{ext}", intent_data.data, mime_type=intent_data.mime_type)
        return result

    # ===== Powers =====

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="analyze_image",
                type=PowerType.MCP,
                description="Analyze an image (dimensions, color, QR codes). Provide base64-encoded image data.",
                input_schema={"type": "object", "properties": {
                    "image_base64": {"type": "string", "description": "Base64-encoded image data"},
                    "mime_type": {"type": "string", "default": "image/jpeg"},
                }, "required": ["image_base64"]},
            ),
            Power(
                name="list_recent_scans",
                type=PowerType.MCP,
                description="List recently scanned/analyzed images",
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "default": 10},
                }},
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        if name == "analyze_image":
            b64 = args.get("image_base64", "")
            if not b64:
                return {"content": [{"type": "text", "text": "No image data provided"}], "is_error": True}
            data = base64.b64decode(b64)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.analyze_image, data, args.get("mime_type", "image/jpeg"))
            lines = [f"{k}: {v}" for k, v in result.items()]
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        if name == "list_recent_scans":
            limit = args.get("limit", 10)
            keys = await self.store.list_keys("scan:")
            keys.sort(reverse=True)
            entries = []
            for k in keys[:limit]:
                e = await self.store.get(k)
                if e:
                    entries.append(f"{e.get('width', '?')}x{e.get('height', '?')} {e.get('format', '?')} ({e.get('size_bytes', 0)} bytes)")
            return {"content": [{"type": "text", "text": "\n".join(entries) or "No scans yet"}]}

        return {"error": f"Unknown power: {name}"}
