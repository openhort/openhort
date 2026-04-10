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
    """Camera llming — enumerate, capture, and manage webcams.

    Owns its own CameraProvider instance — works in both the main
    server and the MCP bridge subprocess (cameras are OS resources).
    Also registers with the global SourceRegistry for stream integration.
    """

    _cam: Any = None  # CameraProvider, created on activate

    def activate(self, config: dict[str, Any]) -> None:
        from hort.media_camera import CameraProvider
        self._cam = CameraProvider()
        # Register with SourceRegistry so sources.list and stream UI can find cameras
        try:
            from hort.media import SourceRegistry
            SourceRegistry.get().register("camera", self._cam)
        except Exception:
            pass
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
        cam = self._cam
        if cam is None:
            return {"content": [{"type": "text", "text": "Camera provider not initialized"}], "is_error": True}

        if name == "list_cameras":
            sources = cam.list_sources()
            lines = []
            for s in sources:
                active = s.metadata.get("active", False)
                status = "🟢 active" if active else "⚪ idle"
                lines.append(f"{s.name} ({s.source_id}) — {status}")
            return {"content": [{"type": "text", "text": "\n".join(lines) or "No cameras found"}]}

        if name == "capture_camera":
            source_id = args.get("source_id", "")
            frame = await cam.capture_frame(source_id)
            if frame is None:
                return {"content": [{"type": "text", "text": f"Failed to capture from {source_id}"}], "is_error": True}
            b64 = base64.b64encode(frame).decode()
            return {"content": [
                {"type": "image", "data": b64, "mimeType": "image/webp"},
                {"type": "text", "text": f"Captured from {source_id} ({len(frame)} bytes)"},
            ]}

        if name == "start_camera":
            source_id = args.get("source_id", "")
            ok = await cam.start_source(source_id)
            return {"content": [{"type": "text", "text": f"Camera {'started' if ok else 'failed to start'}: {source_id}"}]}

        if name == "stop_camera":
            source_id = args.get("source_id", "")
            await cam.stop_source(source_id)
            return {"content": [{"type": "text", "text": f"Camera stopped: {source_id}"}]}

        if name == "camera":
            sources = cam.list_sources()
            if not sources:
                return "No cameras found."
            lines = []
            for s in sources:
                active = s.metadata.get("active", False)
                res = ""
                if active:
                    res = f" {s.metadata.get('width','?')}x{s.metadata.get('height','?')}@{int(s.metadata.get('fps',0))}fps"
                lines.append(f"  {s.name} [{'active' if active else 'idle'}]{res}")
            return "Cameras:\n" + "\n".join(lines)

        return {"error": f"Unknown power: {name}"}

    def get_pulse(self) -> dict[str, Any]:
        if self._cam is None:
            return {"total_cameras": 0, "active_cameras": 0, "cameras": []}
        sources = self._cam.list_sources()
        active = [s for s in sources if s.metadata.get("active", False)]
        return {
            "total_cameras": len(sources),
            "active_cameras": len(active),
            "cameras": [{"name": s.name, "active": s.metadata.get("active", False)} for s in sources],
        }
