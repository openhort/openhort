"""FastAPI routes for the Hort Map — CRUD for hort configs + block catalog."""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import Response

from hort.hortmap.models import BLOCK_CATALOG, HortConfig
from hort.hortmap.store import delete_config, list_configs, load_config, save_config


def create_hortmap_router() -> APIRouter:
    router = APIRouter(prefix="/api/hortmap", tags=["hortmap"])

    @router.get("/catalog")
    async def catalog() -> Response:
        return Response(
            content=json.dumps([b.model_dump() for b in BLOCK_CATALOG]),
            media_type="application/json",
        )

    @router.get("/configs")
    async def list_all() -> Response:
        configs = list_configs()
        return Response(
            content=json.dumps([c.model_dump() for c in configs]),
            media_type="application/json",
        )

    @router.post("/configs")
    async def create(request: Request) -> Response:
        data = await request.json()
        hort_id = data.get("hort_id", "hort_" + secrets.token_urlsafe(6))
        config = HortConfig(hort_id=hort_id, **{k: v for k, v in data.items() if k != "hort_id"})
        save_config(config)
        return Response(content=config.model_dump_json(), media_type="application/json", status_code=201)

    @router.get("/configs/{hort_id}")
    async def get_config(hort_id: str) -> Response:
        config = load_config(hort_id)
        if config is None:
            return Response(content='{"error":"not found"}', media_type="application/json", status_code=404)
        return Response(content=config.model_dump_json(), media_type="application/json")

    @router.put("/configs/{hort_id}")
    async def update_config(hort_id: str, request: Request) -> Response:
        data = await request.json()
        data["hort_id"] = hort_id
        config = HortConfig.model_validate(data)
        save_config(config)
        return Response(content=config.model_dump_json(), media_type="application/json")

    @router.delete("/configs/{hort_id}")
    async def remove_config(hort_id: str) -> Response:
        if delete_config(hort_id):
            return Response(content='{"ok":true}', media_type="application/json")
        return Response(content='{"error":"not found"}', media_type="application/json", status_code=404)

    return router
