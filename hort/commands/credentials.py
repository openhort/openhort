"""WS commands for credential management."""

from __future__ import annotations

from typing import Any

from llming_com import WSRouter

from hort.commands._registry import get_llming_registry

router = WSRouter(prefix="credentials")


@router.handler("status")
async def credential_status(controller: Any, name: str = "") -> dict[str, Any]:
    """Get credential/auth status for a llming."""
    registry = get_llming_registry()
    inst = registry.get_instance(name) if registry else None
    if inst is None:
        return {"name": name, "error": "not found"}
    from hort.ext.credentials import CredentialStore
    creds = getattr(inst, "creds", None)
    if not isinstance(creds, CredentialStore):
        return {"name": name, "auth_required": False}
    return {"name": name, "auth_required": True, **creds.status_dict()}


@router.handler("store")
async def credential_store(controller: Any, name: str = "", token: Any = None) -> dict[str, Any]:
    """Store a credential/token for a llming."""
    registry = get_llming_registry()
    inst = registry.get_instance(name) if registry else None
    from hort.ext.credentials import CredentialStore
    creds = getattr(inst, "creds", None) if inst else None
    if not isinstance(creds, CredentialStore):
        return {"name": name, "ok": False}
    await creds.set_token(
        token=token.get("token", token) if isinstance(token, dict) else token,
        account_name=token.get("account_name", "") if isinstance(token, dict) else "",
        expires_at=token.get("expires_at", 0.0) if isinstance(token, dict) else 0.0,
    )
    return {"name": name, "ok": True, **creds.status_dict()}


@router.handler("revoke")
async def credential_revoke(controller: Any, name: str = "") -> dict[str, Any]:
    """Revoke credentials for a llming."""
    registry = get_llming_registry()
    inst = registry.get_instance(name) if registry else None
    from hort.ext.credentials import CredentialStore
    creds = getattr(inst, "creds", None) if inst else None
    if not isinstance(creds, CredentialStore):
        return {"name": name, "ok": False}
    await creds.clear()
    return {"name": name, "ok": True}
