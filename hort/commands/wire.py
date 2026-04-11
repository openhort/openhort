"""WS commands for chat/wire debugging — send messages, inspect tool calls."""

from __future__ import annotations

import logging
from typing import Any

from llming_com import WSRouter

logger = logging.getLogger(__name__)

router = WSRouter(prefix="wire")


def _get_wire_llming() -> Any:
    from hort.commands._registry import get_llming_registry
    registry = get_llming_registry()
    if not registry:
        return None
    return registry.get_instance("llming-wire")


@router.handler("send")
async def wire_send(controller: Any, text: str = "", cid: str = "debug") -> dict[str, Any]:
    """Send a message through the full chat pipeline and return debug trace.

    Same container, same MCP bridge as normal wire messages.
    """
    if not text:
        return {"error": "no text"}
    wire = _get_wire_llming()
    if not wire:
        return {"error": "llming-wire not loaded"}
    return await wire.debug_send(text, cid)


@router.handler("status")
async def wire_status(controller: Any) -> dict[str, Any]:
    """Check chat backend status — bridge, sessions, tools."""
    wire = _get_wire_llming()
    if not wire:
        return {"error": "llming-wire not loaded"}
    mgr = getattr(wire, "_chat_mgr", None)
    if not mgr:
        return {"status": "not initialized (no messages sent yet)"}

    bridge = getattr(mgr, "_bridge", None)
    sessions = getattr(mgr, "_sessions", {})
    return {
        "bridge_running": bridge is not None and getattr(bridge, "_process", None) is not None,
        "bridge_port": getattr(bridge, "_actual_port", 0) if bridge else 0,
        "sessions": {
            k: {
                "session_id": getattr(s, "_session_id", None),
                "has_container": getattr(s, "_container_session", None) is not None,
            }
            for k, s in sessions.items()
        },
        "system_prompt_len": len(getattr(mgr, "_system_prompt", "")),
    }


@router.handler("reset")
async def wire_reset(controller: Any, cid: str = "debug") -> dict[str, Any]:
    """Reset a chat session (start fresh conversation)."""
    wire = _get_wire_llming()
    if not wire:
        return {"error": "llming-wire not loaded"}
    mgr = getattr(wire, "_chat_mgr", None)
    if mgr:
        mgr.reset_session(f"llming-wire:{cid}")
    return {"ok": True, "cid": cid}
