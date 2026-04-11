"""WS commands for camera management — list, capture, policy, browser devices."""

from __future__ import annotations

from typing import Any

from llming_com import WSRouter

router = WSRouter(prefix="cam")


def _get_cam_llming() -> Any:
    """Get the llming-cam instance from the registry."""
    from hort.commands._registry import get_llming_registry
    registry = get_llming_registry()
    if not registry:
        return None
    return registry.get_instance("llming-cam")


@router.handler("list")
async def cam_list(controller: Any) -> dict[str, Any]:
    """List cameras with full detail + stored thumbnails (for UI)."""
    inst = _get_cam_llming()
    if not inst:
        return {"cameras": []}
    return await inst.execute_power("list_cameras_detailed", {})


@router.handler("policy")
async def cam_policy(controller: Any, source_id: str = "", policy: str = "off") -> dict[str, Any]:
    """Set camera access policy: off, auto, on."""
    import logging
    logging.getLogger(__name__).info("cam.policy: source_id=%s policy=%s", source_id, policy)
    inst = _get_cam_llming()
    if not inst:
        return {"error": "camera provider not available"}
    result = await inst.execute_power("set_camera_policy", {"source_id": source_id, "policy": policy})
    return {"ok": True, "result": result}


@router.handler("capture")
async def cam_capture(controller: Any, source_id: str = "") -> dict[str, Any]:
    """Capture a single frame from a camera."""
    import logging
    logger = logging.getLogger(__name__)
    inst = _get_cam_llming()
    if not inst:
        logger.warning("cam.capture: no llming-cam instance")
        return {"error": "camera provider not available"}
    return await inst.execute_power("capture_camera", {"source_id": source_id})


@router.handler("register_browser")
async def cam_register_browser(controller: Any, devices: list | None = None) -> dict[str, Any]:
    """Register available browser camera devices (called by client after permission grant)."""
    inst = _get_cam_llming()
    if not inst:
        return {"error": "camera provider not available"}
    return await inst.execute_power("register_browser_devices", {"devices": devices or []})
