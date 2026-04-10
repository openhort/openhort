"""WS commands for unified media sources — list, capture."""

from __future__ import annotations

from typing import Any

from llming_com import WSRouter

router = WSRouter(prefix="sources")


@router.handler("list")
async def sources_list(controller: Any, source_type: str = "") -> dict[str, Any]:
    """List all available media sources (windows, screens, cameras, etc.)."""
    from hort.media import SourceRegistry

    registry = SourceRegistry.get()
    sources = registry.list_sources(source_type=source_type)
    return {"data": [
        {
            "source_id": s.source_id,
            "source_type": s.source_type,
            "media_type": s.media_type,
            "name": s.name,
            "metadata": s.metadata,
            "push_mode": s.push_mode,
        }
        for s in sources
    ]}
