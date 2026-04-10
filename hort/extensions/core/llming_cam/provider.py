"""LlmingCam — webcam management for AI and users.

Provides MCP tools and slash commands for camera enumeration,
capture, and lifecycle management. Cameras are on-demand — they
only open when explicitly started or when a frame is requested.
"""

from __future__ import annotations

import base64
from typing import Any

from hort.llming import LlmingBase, Power, PowerType


class LlmingCam(LlmingBase):
    """Camera llming — enumerate, capture, and manage webcams."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("LlmingCam activated")

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="list_cameras",
                type=PowerType.MCP,
                description="List available cameras (webcams, virtual cameras). Zero cost — does not open devices.",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="capture_camera",
                type=PowerType.MCP,
                description=(
                    "Capture a single frame from a camera. Auto-starts the camera if not active. "
                    "Returns a WebP image. Use list_cameras first to get source_id."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_id": {
                            "type": "string",
                            "description": "Camera source ID from list_cameras (e.g. 'cam:FaceTime HD')",
                        },
                    },
                    "required": ["source_id"],
                },
            ),
            Power(
                name="start_camera",
                type=PowerType.MCP,
                description="Explicitly start a camera (opens device, begins capturing). Ref-counted.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "description": "Camera source ID"},
                    },
                    "required": ["source_id"],
                },
            ),
            Power(
                name="stop_camera",
                type=PowerType.MCP,
                description="Stop a camera (closes device). Only closes when last viewer disconnects.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "description": "Camera source ID"},
                    },
                    "required": ["source_id"],
                },
            ),
            Power(
                name="camera",
                type=PowerType.COMMAND,
                description="List cameras and their status",
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        from hort.media import SourceRegistry

        registry = SourceRegistry.get()
        cam_provider = registry.get_provider("camera")

        if name == "list_cameras":
            sources = registry.list_sources(source_type="camera")
            lines = []
            for s in sources:
                active = s.metadata.get("active", False)
                status = "🟢 active" if active else "⚪ idle"
                lines.append(f"{s.name} ({s.source_id}) — {status}")
            text = "\n".join(lines) if lines else "No cameras found"
            return {"content": [{"type": "text", "text": text}]}

        if name == "capture_camera":
            source_id = args.get("source_id", "")
            if not cam_provider:
                return {"content": [{"type": "text", "text": "Camera provider not available"}], "is_error": True}

            frame = await cam_provider.capture_frame(source_id)
            if frame is None:
                return {"content": [{"type": "text", "text": f"Failed to capture from {source_id}"}], "is_error": True}

            b64 = base64.b64encode(frame).decode()
            return {"content": [
                {"type": "image", "data": b64, "mimeType": "image/webp"},
                {"type": "text", "text": f"Captured from {source_id} ({len(frame)} bytes)"},
            ]}

        if name == "start_camera":
            source_id = args.get("source_id", "")
            if not cam_provider:
                return {"content": [{"type": "text", "text": "Camera provider not available"}], "is_error": True}
            ok = await cam_provider.start_source(source_id)
            return {"content": [{"type": "text", "text": f"Camera {'started' if ok else 'failed to start'}: {source_id}"}]}

        if name == "stop_camera":
            source_id = args.get("source_id", "")
            if not cam_provider:
                return {"content": [{"type": "text", "text": "Camera provider not available"}], "is_error": True}
            await cam_provider.stop_source(source_id)
            return {"content": [{"type": "text", "text": f"Camera stopped: {source_id}"}]}

        if name == "camera":
            sources = registry.list_sources(source_type="camera")
            if not sources:
                return "No cameras found."
            lines = []
            for s in sources:
                active = s.metadata.get("active", False)
                status = "active" if active else "idle"
                res = ""
                if active:
                    w = s.metadata.get("width", "?")
                    h = s.metadata.get("height", "?")
                    fps = s.metadata.get("fps", "?")
                    res = f" {w}x{h}@{fps}fps"
                lines.append(f"  {s.name} [{status}]{res}")
            return "Cameras:\n" + "\n".join(lines)

        return {"error": f"Unknown power: {name}"}

    def get_pulse(self) -> dict[str, Any]:
        from hort.media import SourceRegistry
        registry = SourceRegistry.get()
        sources = registry.list_sources(source_type="camera")
        active = [s for s in sources if s.metadata.get("active", False)]
        return {
            "total_cameras": len(sources),
            "active_cameras": len(active),
            "cameras": [{"name": s.name, "active": s.metadata.get("active", False)} for s in sources],
        }
