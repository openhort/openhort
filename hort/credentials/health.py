"""Credential health checker — background validation + auto-refresh.

Runs periodically (default: every 5 minutes) and checks:
1. Token expiry (< 1 hour remaining → try refresh → alert if fails)
2. Endpoint health (validate_url returns non-2xx → alert)
3. Status transitions (valid → expiring → expired)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from hort.credentials.types import (
    CredentialAlert,
    CredentialSpec,
    CredentialStatus,
    CredentialType,
)

logger = logging.getLogger(__name__)

# How soon before expiry to start warning (seconds)
EXPIRY_WARNING_THRESHOLD = 3600  # 1 hour


async def check_all_credentials(
    manager: Any,  # CredentialManager (avoid circular import)
) -> list[CredentialAlert]:
    """Check all stored credentials for health issues.

    Returns a list of new alerts. Also updates credential status
    in the vault and attempts auto-refresh where supported.
    """
    alerts: list[CredentialAlert] = []

    for info in manager.list_all():
        if info.status in (CredentialStatus.REVOKED, CredentialStatus.UNCONFIGURED):
            continue

        # Check expiry
        if info.expires_at:
            try:
                expires = datetime.fromisoformat(info.expires_at)
                now = datetime.now(timezone.utc)
                remaining = (expires - now).total_seconds()

                if remaining <= 0:
                    # Expired — try refresh
                    refreshed = await _try_refresh(manager, info)
                    if not refreshed:
                        manager._vault.update_status(
                            info.llming_name, info.credential_id,
                            CredentialStatus.EXPIRED,
                        )
                        alerts.append(CredentialAlert(
                            llming_name=info.llming_name,
                            credential_id=info.credential_id,
                            label=info.label or info.credential_id,
                            status=CredentialStatus.EXPIRED,
                            message="Token expired. Re-authenticate to continue.",
                        ))

                elif remaining < EXPIRY_WARNING_THRESHOLD:
                    # Expiring soon — try refresh proactively
                    refreshed = await _try_refresh(manager, info)
                    if not refreshed:
                        manager._vault.update_status(
                            info.llming_name, info.credential_id,
                            CredentialStatus.EXPIRING,
                        )
                        minutes = int(remaining / 60)
                        alerts.append(CredentialAlert(
                            llming_name=info.llming_name,
                            credential_id=info.credential_id,
                            label=info.label or info.credential_id,
                            status=CredentialStatus.EXPIRING,
                            message=f"Token expires in {minutes} minutes.",
                        ))

            except (ValueError, TypeError):
                pass  # invalid date format — skip

        # Endpoint health check
        specs = manager.get_specs(info.llming_name)
        spec = next((s for s in specs if s.id == info.credential_id), None)
        if spec and spec.validate_url and info.status == CredentialStatus.VALID:
            healthy = await _check_endpoint(manager, info, spec)
            if not healthy:
                manager._vault.update_status(
                    info.llming_name, info.credential_id,
                    CredentialStatus.ERROR,
                )
                alerts.append(CredentialAlert(
                    llming_name=info.llming_name,
                    credential_id=info.credential_id,
                    label=info.label or info.credential_id,
                    status=CredentialStatus.ERROR,
                    message="Validation failed. Check credentials.",
                    action="retry",
                ))

    return alerts


async def _try_refresh(manager: Any, info: Any) -> bool:
    """Attempt to refresh an OAuth2 token. Returns True if successful."""
    if info.credential_type != CredentialType.OAUTH2:
        return False

    cred_value = manager.get(info.llming_name, info.credential_id)
    if not cred_value or "refresh_token" not in cred_value:
        return False

    specs = manager.get_specs(info.llming_name)
    spec = next((s for s in specs if s.id == info.credential_id), None)
    if not spec or not spec.refresh_supported:
        return False

    try:
        from hort.credentials.oauth import refresh_token
        new_tokens = await refresh_token(
            spec, cred_value["refresh_token"],
        )
        if "access_token" in new_tokens:
            # Update stored credential with new tokens
            cred_value["access_token"] = new_tokens["access_token"]
            if "refresh_token" in new_tokens:
                cred_value["refresh_token"] = new_tokens["refresh_token"]

            # Calculate new expiry
            expires_in = new_tokens.get("expires_in", 3600)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

            manager.set(
                info.llming_name, info.credential_id, cred_value,
                credential_type=CredentialType.OAUTH2,
                expires_at=expires_at,
            )
            logger.info(
                "Refreshed token for %s:%s (expires in %ds)",
                info.llming_name, info.credential_id, expires_in,
            )
            return True
    except Exception as exc:
        logger.debug("Token refresh failed for %s:%s: %s",
                     info.llming_name, info.credential_id, exc)

    return False


async def _check_endpoint(manager: Any, info: Any, spec: CredentialSpec) -> bool:
    """Validate a credential against its endpoint. Returns True if healthy."""
    cred_value = manager.get(info.llming_name, info.credential_id)
    if not cred_value:
        return False

    try:
        if spec.type == CredentialType.API_KEY:
            from hort.credentials.oauth import validate_api_key
            key = cred_value.get("value", "")
            return await validate_api_key(spec, key)

        elif spec.type == CredentialType.OAUTH2:
            from hort.credentials.oauth import validate_api_key
            token = cred_value.get("access_token", "")
            return await validate_api_key(spec, token)

        elif spec.type == CredentialType.BEARER_TOKEN:
            from hort.credentials.oauth import validate_api_key
            token = cred_value.get("value", cred_value.get("token", ""))
            return await validate_api_key(spec, token)

        elif spec.type == CredentialType.USERNAME_PASSWORD:
            from hort.credentials.oauth import validate_username_password
            return await validate_username_password(
                spec, cred_value.get("username", ""), cred_value.get("password", ""),
            )

    except Exception as exc:
        logger.debug("Health check failed for %s:%s: %s",
                     info.llming_name, info.credential_id, exc)

    return False
