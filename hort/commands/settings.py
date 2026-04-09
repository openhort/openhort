"""WS commands for system settings."""

from __future__ import annotations

import asyncio
from typing import Any

from llming_com import WSRouter

router = WSRouter(prefix="settings")


@router.handler("apply")
async def settings_apply(controller: Any) -> dict[str, Any]:
    """Apply system settings (caffeinate, display sleep)."""
    from hort.plugins import apply_power_settings
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, apply_power_settings)
    return {"ok": True}
