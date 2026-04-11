"""Screenshot Capture plugin — captures screenshots and serves them to the client.

Demonstrates the **server→client image flow**:
1. Server captures a screenshot (via PIL/Quartz or subprocess)
2. Stores it in the plugin's file store (with optional TTL)
3. Serves it to the browser via a custom FastAPI endpoint
4. Browser displays it in an image gallery

The key pattern: ``self.files.save()`` stores binary data,
and a FastAPI router endpoint serves it back via ``self.files.load()``.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from hort.llming import Llming, Power, PowerType


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine from sync context."""
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


class ScreenshotCapture(Llming):
    """Captures screenshots and serves them to the browser."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Screenshot capture plugin activated")

    def capture_screenshot(self) -> None:
        """Capture a screenshot. Runs in executor thread."""
        try:
            # Use screencapture on macOS (fast, no extra deps)
            import platform
            ts = int(time.time())
            filename = f"screenshot_{ts}.png"

            if platform.system() == "Darwin":
                # macOS: screencapture to temp file
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                subprocess.run(
                    ["screencapture", "-x", "-C", tmp_path],
                    timeout=5, check=True,
                )
                from pathlib import Path
                data = Path(tmp_path).read_bytes()
                Path(tmp_path).unlink(missing_ok=True)
            else:
                # Linux fallback: use PIL
                from PIL import ImageGrab
                import io
                img = ImageGrab.grab()
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                data = buf.getvalue()

            # Store in file store with 1h TTL
            _run_coro(self.files.save(
                filename, data,
                mime_type="image/png",
                ttl_seconds=3600,
            ))

            # Update latest reference
            _run_coro(self.store.put("latest_screenshot", {
                "filename": filename,
                "timestamp": ts,
                "size": len(data),
            }))

            self.log.info("Screenshot captured: %s (%d bytes)", filename, len(data))

        except Exception as e:
            self.log.error("Screenshot capture failed: %s", e)

    # ===== FastAPI Router (serves images to browser) =====

    def get_router(self) -> APIRouter:
        """Custom endpoint to serve screenshot images."""
        router = APIRouter()
        plugin = self  # capture reference

        @router.get("/screenshots")
        async def list_screenshots() -> Response:
            """List all available screenshots."""
            import json
            files = await plugin.files.list_files("screenshot_")
            items = [
                {"name": f.name, "size": f.size, "created": f.created_at}
                for f in sorted(files, key=lambda f: f.created_at, reverse=True)
            ]
            return Response(content=json.dumps(items), media_type="application/json")

        @router.get("/screenshots/{filename}")
        async def get_screenshot(filename: str) -> Response:
            """Serve a screenshot image."""
            result = await plugin.files.load(filename)
            if result is None:
                return Response(content="Not found", status_code=404)
            data, mime = result
            return Response(content=data, media_type=mime or "image/png")

        @router.post("/capture")
        async def trigger_capture() -> Response:
            """Trigger an on-demand screenshot capture."""
            import json
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, plugin.capture_screenshot)
            latest = await plugin.store.get("latest_screenshot")
            return Response(
                content=json.dumps({"ok": True, "screenshot": latest}),
                media_type="application/json",
            )

        return router

    # ===== Powers =====

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="capture_screenshot",
                type=PowerType.MCP,
                description="Take a screenshot of the remote machine's screen",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="list_screenshots",
                type=PowerType.MCP,
                description="List recently captured screenshots",
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "default": 10},
                }},
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        if name == "capture_screenshot":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.capture_screenshot)
            latest = await self.store.get("latest_screenshot")
            if latest:
                return {"content": [{"type": "text", "text": f"Screenshot captured: {latest['filename']} ({latest['size']} bytes)"}]}
            return {"content": [{"type": "text", "text": "Screenshot capture failed"}], "is_error": True}

        if name == "list_screenshots":
            limit = args.get("limit", 10)
            files = await self.files.list_files("screenshot_")
            files_sorted = sorted(files, key=lambda f: f.created_at, reverse=True)[:limit]
            if not files_sorted:
                return {"content": [{"type": "text", "text": "No screenshots available"}]}
            lines = [f"{f.name} ({f.size} bytes, {time.strftime('%H:%M:%S', time.localtime(f.created_at))})" for f in files_sorted]
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        return {"error": f"Unknown power: {name}"}
