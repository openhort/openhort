"""WS commands for messaging connectors."""

from __future__ import annotations

from typing import Any

from llming_com import WSRouter

from hort.commands._registry import get_llming_registry

router = WSRouter(prefix="connectors")


@router.handler("list")
async def connectors_list(controller: Any) -> dict[str, Any]:
    """List messaging connectors and their status."""
    from hort.ext.connectors import ConnectorBase

    registry = get_llming_registry()
    messaging: dict[str, Any] = {}
    if registry:
        for name, inst in registry._instances.items():
            if isinstance(inst, ConnectorBase):
                status = inst.vault.get("state") if hasattr(inst, "vault") else {}
                messaging[inst.connector_id] = {
                    "active": status.get("active", False),
                    "llming_id": name,
                    **status,
                }
    return {"data": messaging}
