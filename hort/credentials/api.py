"""Credential REST API — setup, validation, alerts, OAuth callbacks.

Mounted at ``/api/credentials/`` in the FastAPI app. Provides endpoints
for the UI to configure credentials, check status, and handle OAuth
redirects. All sensitive operations are localhost-only unless the
credential spec allows remote updates.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from hort.credentials.manager import get_credential_manager
from hort.credentials.types import CredentialStatus, CredentialType

logger = logging.getLogger(__name__)


def build_credential_router() -> APIRouter:
    """Create the credential management API router."""
    router = APIRouter()
    manager = get_credential_manager()

    # ===== List & Status =====

    @router.get("/credentials")
    async def list_credentials() -> JSONResponse:
        """List all credentials with their status (no secret values)."""
        creds = manager.list_all()
        return JSONResponse({
            "credentials": [
                {
                    "llming": c.llming_name,
                    "id": c.credential_id,
                    "type": c.credential_type.value,
                    "status": c.status.value,
                    "label": c.label,
                    "expires_at": c.expires_at,
                    "provider": c.provider,
                    "remote_update": c.remote_update,
                }
                for c in creds
            ],
        })

    @router.get("/credentials/{llming}/{cred_id}")
    async def get_credential_info(llming: str, cred_id: str) -> JSONResponse:
        """Get credential metadata (no secret values)."""
        info = manager.info(llming, cred_id)
        if not info:
            raise HTTPException(404, "Credential not found")
        return JSONResponse({
            "llming": info.llming_name,
            "id": info.credential_id,
            "type": info.credential_type.value,
            "status": info.status.value,
            "label": info.label,
            "created_at": info.created_at,
            "updated_at": info.updated_at,
            "expires_at": info.expires_at,
            "provider": info.provider,
            "scopes": info.scopes,
            "remote_update": info.remote_update,
        })

    # ===== Alerts =====

    @router.get("/credentials/alerts")
    async def get_alerts() -> JSONResponse:
        """Get active credential alerts (expired, errors)."""
        alerts = manager.get_alerts()
        # Also check the vault for expired credentials
        expired = manager._vault.list_expired()
        return JSONResponse({
            "alerts": [
                {
                    "llming": a.llming_name,
                    "id": a.credential_id,
                    "label": a.label,
                    "status": a.status.value,
                    "message": a.message,
                    "action": a.action,
                    "timestamp": a.timestamp,
                }
                for a in alerts
            ],
            "expired_count": len(expired),
        })

    # ===== Unconfigured =====

    @router.get("/credentials/unconfigured")
    async def get_unconfigured() -> JSONResponse:
        """List credentials that need initial setup."""
        unconfigured = manager.get_unconfigured()
        return JSONResponse({
            "unconfigured": [
                {
                    "llming": llming_name,
                    "id": spec.id,
                    "type": spec.type.value,
                    "label": spec.label,
                    "provider": spec.provider,
                    "required": spec.required,
                    "help_url": spec.help_url,
                    "help_text": spec.help_text,
                }
                for llming_name, spec in unconfigured
            ],
        })

    # ===== Set Credential (API Key, Bearer Token, Username/Password) =====

    @router.post("/credentials/{llming}/{cred_id}")
    async def set_credential(
        llming: str, cred_id: str, request: Request,
    ) -> JSONResponse:
        """Store a credential value. Validates if possible."""
        # Check remote update policy
        if _is_remote(request):
            specs = manager.get_specs(llming)
            spec = next((s for s in specs if s.id == cred_id), None)
            if spec and not spec.remote_update:
                raise HTTPException(403, "This credential can only be updated locally")

        body = await request.json()
        cred_type_str = body.get("type", "api_key")
        cred_type = CredentialType(cred_type_str)
        value = body.get("value", {})
        expires_at = body.get("expires_at")
        metadata = body.get("metadata", {})

        # Validate before storing
        valid = True
        specs = manager.get_specs(llming)
        spec = next((s for s in specs if s.id == cred_id), None)

        if spec and spec.validate_url:
            try:
                from hort.credentials.oauth import validate_api_key, validate_username_password
                if cred_type in (CredentialType.API_KEY, CredentialType.BEARER_TOKEN):
                    key = value.get("value", value.get("token", ""))
                    valid = await validate_api_key(spec, key)
                elif cred_type == CredentialType.USERNAME_PASSWORD:
                    valid = await validate_username_password(
                        spec, value.get("username", ""), value.get("password", ""),
                    )
            except Exception:
                logger.exception("Credential validation failed")
                valid = False

        if not valid:
            return JSONResponse({"ok": False, "error": "Validation failed"}, status_code=400)

        manager.set(
            llming, cred_id, value,
            credential_type=cred_type,
            expires_at=expires_at,
            metadata=metadata,
        )
        return JSONResponse({"ok": True, "status": "valid"})

    # ===== Revoke =====

    @router.delete("/credentials/{llming}/{cred_id}")
    async def revoke_credential(llming: str, cred_id: str) -> JSONResponse:
        """Revoke and clear a credential."""
        manager.revoke(llming, cred_id)
        return JSONResponse({"ok": True})

    # ===== OAuth2 Flow =====

    @router.post("/credentials/{llming}/{cred_id}/oauth/start")
    async def start_oauth(
        llming: str, cred_id: str, request: Request,
    ) -> JSONResponse:
        """Start an OAuth2 flow. Returns auth URL (local) or device code (remote)."""
        specs = manager.get_specs(llming)
        spec = next((s for s in specs if s.id == cred_id), None)
        if not spec or spec.type != CredentialType.OAUTH2:
            raise HTTPException(400, "Not an OAuth2 credential")

        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        tenant = body.get("tenant", "")

        if _is_remote(request):
            # Device code flow for remote users
            from hort.credentials.oauth import start_device_code_flow
            try:
                result = await start_device_code_flow(spec, tenant=tenant)
                return JSONResponse({
                    "flow": "device_code",
                    "user_code": result.get("user_code"),
                    "verification_uri": result.get("verification_uri"),
                    "expires_in": result.get("expires_in", 900),
                    "message": result.get("message", ""),
                })
            except Exception:
                logger.exception("Device code flow failed")
                raise HTTPException(502, "Failed to start device code flow")
        else:
            # Localhost redirect flow
            from hort.credentials.oauth import build_auth_url
            try:
                auth_url, state = build_auth_url(spec, tenant=tenant)
                return JSONResponse({
                    "flow": "redirect",
                    "auth_url": auth_url,
                    "state": state,
                })
            except Exception:
                logger.exception("OAuth URL build failed")
                raise HTTPException(502, "Failed to build auth URL")

    @router.get("/auth/callback")
    async def oauth_callback(request: Request) -> HTMLResponse:
        """OAuth2 redirect callback. Exchanges code for tokens."""
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        error = request.query_params.get("error", "")

        if error:
            return HTMLResponse(
                f"<h2>Authentication failed</h2><p>{error}</p>"
                "<p><a href='/'>Back to openhort</a></p>",
                status_code=400,
            )

        if not code or not state:
            return HTMLResponse(
                "<h2>Invalid callback</h2><p>Missing code or state parameter.</p>",
                status_code=400,
            )

        try:
            from hort.credentials.oauth import exchange_code, _pending_flows
            # Find which llming/credential this flow belongs to
            flow = _pending_flows.get(state)
            if not flow:
                return HTMLResponse(
                    "<h2>Expired</h2><p>This authentication session has expired. Try again.</p>",
                    status_code=400,
                )

            spec: Any = flow["spec"]
            tokens = await exchange_code(state, code)

            if "access_token" not in tokens:
                return HTMLResponse(
                    "<h2>Failed</h2><p>No access token received.</p>",
                    status_code=502,
                )

            # Find the llming name from registered specs
            llming_name = ""
            for name, specs in manager._specs.items():
                if spec in specs:
                    llming_name = name
                    break

            if not llming_name:
                return HTMLResponse(
                    "<h2>Error</h2><p>Could not find the llming for this credential.</p>",
                    status_code=500,
                )

            # Calculate expiry
            from datetime import datetime, timedelta, timezone
            expires_in = tokens.get("expires_in", 3600)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

            # Store tokens
            manager.set(
                llming_name, spec.id, tokens,
                credential_type=CredentialType.OAUTH2,
                expires_at=expires_at,
                metadata={
                    "provider": spec.provider,
                    "scopes": spec.scopes,
                    "label": spec.label,
                },
            )

            return HTMLResponse(
                "<h2>Connected!</h2>"
                f"<p>Successfully authenticated <b>{spec.label or spec.id}</b>.</p>"
                "<p>You can close this window.</p>"
                "<script>setTimeout(() => window.close(), 3000)</script>",
            )

        except Exception:
            logger.exception("OAuth callback failed")
            return HTMLResponse(
                "<h2>Error</h2><p>Something went wrong during authentication.</p>",
                status_code=500,
            )

    # ===== Helpers =====

    def _is_remote(request: Request) -> bool:
        """Check if the request comes from a remote source."""
        forwarded_via = request.headers.get("x-forwarded-via", "")
        return forwarded_via in ("proxy", "p2p")

    return router
