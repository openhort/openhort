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
        import asyncio
        from hort.media_camera import CameraProvider
        self._cam = CameraProvider()
        # Register with SourceRegistry so sources.list and stream UI can find cameras
        try:
            from hort.media import SourceRegistry
            SourceRegistry.get().register("camera", self._cam)
        except Exception:
            pass
        # Restore previously active cameras from persistent store
        self._restore_wanted()
        self.log.info("LlmingCam activated")

    def _restore_wanted(self) -> None:
        """Restore cameras that were active before restart."""
        import asyncio

        async def _restore() -> None:
            wanted = await self.store.get("wanted_cameras")
            if wanted and isinstance(wanted, dict):
                # Restore policies first
                policies = wanted.get("policies", {})
                for sid, policy in policies.items():
                    self._cam.set_policy(sid, policy)
                # Restore active cameras
                ids = wanted.get("ids", [])
                for source_id in ids:
                    self.log.info("Restoring camera: %s", source_id)
                    ok = await self._cam.start_source(source_id)
                    if ok:
                        self.log.info("Camera restored: %s", source_id)
                    else:
                        self.log.warning("Camera not available for restore: %s", source_id)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_restore())
            else:
                loop.run_until_complete(_restore())
        except Exception:
            pass

    async def _persist_wanted(self) -> None:
        """Save wanted cameras and policies to persistent store."""
        if self._cam:
            await self.store.put("wanted_cameras", {
                "ids": list(self._cam._wanted),
                "policies": dict(self._cam._policies),
            })

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
                    "Capture a single frame from a camera. If the camera policy is 'auto', "
                    "the camera opens temporarily and closes after 10 seconds of inactivity. "
                    "If 'off', capture is blocked. If 'on', camera is already running. "
                    "No need to call start_camera first — just capture directly. "
                    "Use list_cameras to see available cameras and their policy."
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
                name="set_camera_policy",
                type=PowerType.MCP,
                description="Set camera access policy: 'off' (disabled), 'auto' (AI can one-shot), 'on' (always running)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "policy": {"type": "string", "enum": ["off", "auto", "on"]},
                    },
                    "required": ["source_id", "policy"],
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

        if name == "list_cameras_detailed":
            # Structured data for UI — not MCP text
            sources = cam.list_sources()
            return {"cameras": [
                {
                    "source_id": s.source_id,
                    "name": s.name,
                    "metadata": s.metadata,
                }
                for s in sources
            ]}

        if name == "list_cameras":
            sources = cam.list_sources()
            lines = []
            for s in sources:
                active = s.metadata.get("active", False)
                policy = s.metadata.get("policy", "off")
                status = "🟢 on" if active else f"⚪ {policy}"
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
            await self._persist_wanted()
            return {"content": [{"type": "text", "text": f"Camera {'started' if ok else 'failed to start'}: {source_id}"}]}

        if name == "stop_camera":
            source_id = args.get("source_id", "")
            await cam.stop_source(source_id)
            await self._persist_wanted()
            return {"content": [{"type": "text", "text": f"Camera stopped: {source_id}"}]}

        if name == "set_camera_policy":
            source_id = args.get("source_id", "")
            policy = args.get("policy", "off")
            cam.set_policy(source_id, policy)
            # If setting to "on", start the camera; if "off", stop it
            if policy == "on":
                await cam.start_source(source_id)
            elif policy == "off":
                await cam.stop_source(source_id)
                cam._wanted.discard(source_id)  # truly off
            await self._persist_wanted()
            return {"content": [{"type": "text", "text": f"Camera {source_id} policy set to '{policy}'"}]}

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
