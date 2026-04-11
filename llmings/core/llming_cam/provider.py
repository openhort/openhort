"""LlmingCam — webcam management for AI and users.

Provides MCP tools and slash commands for camera enumeration,
capture, and lifecycle management. Cameras are on-demand — they
only open when explicitly started or when a frame is requested.
"""

from __future__ import annotations

import base64
from typing import Any

from hort.llming import Llming, Power, PowerType


class LlmingCam(Llming):
    """Camera llming — enumerate, capture, and manage webcams.

    Owns its own CameraProvider instance — works in both the main
    server and the MCP bridge subprocess (cameras are OS resources).
    Also registers with the global SourceRegistry for stream integration.
    """

    _cam: Any = None  # CameraProvider, created on activate

    def activate(self, config: dict[str, Any]) -> None:
        import asyncio
        from llmings.core.llming_cam.camera import CameraProvider
        self._cam = CameraProvider()
        # Register with SourceRegistry so sources.list and stream UI can find cameras
        try:
            from hort.media import SourceRegistry
            SourceRegistry.get().register("camera", self._cam)
        except Exception:
            pass
        # Restore previously active native cameras from persistent store
        self._restore_wanted()
        self.log.info("LlmingCam activated")

    async def on_viewer_connect(self, session_id: str, controller: Any) -> None:
        """Viewer connected — signal browser to start any 'on' browser cameras."""
        if not self._cam:
            return
        # Check for browser cameras with policy "on" that aren't active
        for source_id, policy in dict(self._cam._policies).items():
            if source_id.startswith("cam:browser_") and policy == "on":
                if not self._cam.is_active(source_id):
                    self.log.info("Requesting browser camera start: %s", source_id)
                    try:
                        await controller.send_ui_action("start_browser_camera", source_id=source_id)
                    except Exception:
                        pass

    async def on_viewer_disconnect(self, session_id: str) -> None:
        """Viewer disconnected — clean up browser camera sessions for this viewer."""
        if not self._cam:
            return
        for source_id in list(self._cam._sessions):
            session = self._cam._sessions.get(source_id)
            if session and getattr(session, '_session_id', '') == session_id:
                self.log.info("Cleaning up browser camera: %s (viewer disconnected)", source_id)
                session.stop()
                self._cam._sessions.pop(source_id, None)

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
                # Start native cameras that should be running (skip browser cams)
                to_start = set(wanted.get("ids", []))
                for sid, policy in policies.items():
                    if policy == "on":
                        to_start.add(sid)
                to_start = {s for s in to_start if not s.startswith("cam:browser_")}
                for source_id in to_start:
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

    async def _save_thumb(self, source_id: str, b64: str) -> None:
        """Save a small thumbnail for a camera (survives restart, shows when off).

        Resizes to 320px wide to keep storage small (~5-15KB).
        """
        try:
            import base64 as b64mod, io
            from PIL import Image
            raw = b64mod.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            # Resize to thumbnail
            if img.width > 320:
                ratio = 320 / img.width
                img = img.resize((320, int(img.height * ratio)), Image.Resampling.BILINEAR)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=60, method=0)
            img.close()
            thumb_b64 = b64mod.b64encode(buf.getvalue()).decode()
            buf.close()
            await self.store.put(f"thumb:{source_id}", {"b64": thumb_b64})
        except Exception:
            pass  # non-critical — just won't have a stored thumb

    async def _get_thumb(self, source_id: str) -> str:
        """Get stored thumbnail for a camera."""
        data = await self.store.get(f"thumb:{source_id}")
        return data.get("b64", "") if data else ""

    async def _persist_wanted(self) -> None:
        """Save wanted cameras and policies to persistent store."""
        if self._cam:
            await self.store.put("wanted_cameras", {
                "ids": list(self._cam._wanted),
                "policies": dict(self._cam._policies),
            })

    async def _start_browser_camera(self, source_id: str) -> None:
        """Signal browser client to start streaming a specific camera."""
        from hort.session import HortRegistry
        registry = HortRegistry.get()
        for entry in registry._sessions.values():
            ctrl = getattr(entry, "controller", None)
            if ctrl and hasattr(ctrl, "send_ui_action"):
                self.log.info("Signaling browser to start camera: %s", source_id)
                await ctrl.send_ui_action("start_browser_camera", source_id=source_id)
                return
        self.log.warning("No browser session found to start camera: %s", source_id)

    async def _stop_browser_camera(self, source_id: str) -> None:
        """Signal browser client to stop a specific browser camera."""
        from hort.session import HortRegistry
        cam = self._cam
        if cam:
            session = cam._sessions.pop(source_id, None)
            if session:
                session.stop()
        registry = HortRegistry.get()
        for entry in registry._sessions.values():
            ctrl = getattr(entry, "controller", None)
            if ctrl and hasattr(ctrl, "send_ui_action"):
                await ctrl.send_ui_action("stop_browser_camera", source_id=source_id)
                return

    def _sync_vault(self) -> None:
        """Write current camera state to vault."""
        if self._cam is None:
            self.vault.set("state", {"total_cameras": 0, "active_cameras": 0, "cameras": []})
            return
        sources = self._cam.list_sources()
        active = [s for s in sources if s.metadata.get("active", False)]
        self.vault.set("state", {
            "total_cameras": len(sources),
            "active_cameras": len(active),
            "cameras": [{"name": s.name, "active": s.metadata.get("active", False)} for s in sources],
        })

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="list_cameras",
                type=PowerType.MCP,
                description=(
                    "List available cameras and their policy. Policies are set by the user: "
                    "'off' = disabled, 'auto' = you can capture on demand, 'on' = always running. "
                    "You CANNOT change policies — only capture from cameras the user enabled."
                ),
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="capture_camera",
                type=PowerType.MCP,
                description=(
                    "Capture a single frame from a camera. Only works if the user set the "
                    "camera policy to 'auto' or 'on'. If 'auto', the camera opens temporarily. "
                    "If 'off', capture is blocked. Use list_cameras to check policy first."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_id": {
                            "type": "string",
                            "description": "Camera source ID from list_cameras",
                        },
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

        if name == "register_browser_devices":
            # Client reports available browser camera devices
            devices = args.get("devices", [])
            registered = []
            for dev in devices:
                device_id = dev.get("deviceId", "")
                label = dev.get("label", "Browser Camera")
                if not device_id:
                    continue
                source_id = f"cam:browser_{device_id[:12]}"
                # Register as idle source (not streaming)
                cam.register_browser_device(source_id, label)
                registered.append(source_id)
            return {"registered": registered}

        if name == "list_cameras_detailed":
            # Structured data for UI — includes stored thumbnails
            sources = cam.list_sources()
            cameras = []
            for s in sources:
                thumb = await self._get_thumb(s.source_id)
                cameras.append({
                    "source_id": s.source_id,
                    "name": s.name,
                    "metadata": s.metadata,
                    "thumb": thumb,  # last-known frame (even when off)
                })
            return {"cameras": cameras}

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
            # Browser camera in auto mode: signal client to start, wait for frames
            if source_id.startswith("cam:browser_") and not cam.is_active(source_id):
                policy = cam.get_policy(source_id)
                if policy == "off":
                    return {"content": [{"type": "text", "text": f"Camera {source_id} is disabled (policy: off)"}], "is_error": True}
                await self._start_browser_camera(source_id)
                import asyncio
                for _ in range(30):
                    await asyncio.sleep(0.1)
                    if cam.is_active(source_id):
                        session = cam._sessions.get(source_id)
                        if session and session._latest_frame:
                            break
            frame = await cam.capture_frame(source_id)
            if frame is None:
                return {"content": [{"type": "text", "text": f"Failed to capture from {source_id}"}], "is_error": True}
            b64 = base64.b64encode(frame).decode()
            # Persist thumbnail for offline display
            await self._save_thumb(source_id, b64)
            return {"content": [
                {"type": "image", "data": b64, "mimeType": "image/webp"},
                {"type": "text", "text": f"Captured from {source_id} at {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({len(frame)} bytes)"},
            ]}

        if name == "start_camera":
            source_id = args.get("source_id", "")
            ok = await cam.start_source(source_id)
            await self._persist_wanted()
            self._sync_vault()
            return {"content": [{"type": "text", "text": f"Camera {'started' if ok else 'failed to start'}: {source_id}"}]}

        if name == "stop_camera":
            source_id = args.get("source_id", "")
            await cam.stop_source(source_id)
            await self._persist_wanted()
            self._sync_vault()
            return {"content": [{"type": "text", "text": f"Camera stopped: {source_id}"}]}

        if name == "set_camera_policy":
            source_id = args.get("source_id", "")
            policy = args.get("policy", "off")
            cam.set_policy(source_id, policy)
            if policy == "on":
                # Check if it's a browser camera — signal client to start
                if source_id.startswith("cam:browser_"):
                    await self._start_browser_camera(source_id)
                else:
                    await cam.start_source(source_id)
            elif policy == "auto":
                # Auto = available for AI, but not actively running
                if source_id.startswith("cam:browser_"):
                    await self._stop_browser_camera(source_id)
                elif cam.is_active(source_id):
                    await cam.stop_source(source_id)
                cam._wanted.discard(source_id)
            elif policy == "off":
                if source_id.startswith("cam:browser_"):
                    await self._stop_browser_camera(source_id)
                else:
                    await cam.stop_source(source_id)
                cam._wanted.discard(source_id)
            await self._persist_wanted()
            self._sync_vault()
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
