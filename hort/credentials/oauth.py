"""OAuth2 flow handler — localhost redirect + device code flow.

Supports two modes:
- **Localhost redirect** — browser opens auth URL, provider redirects
  to ``localhost:8940/auth/callback``. Only works on the local machine.
- **Device code** — user visits a URL and enters a code. Works from
  any device (Telegram, remote proxy, P2P).

The mode is selected automatically based on whether the request comes
from localhost (redirect) or remote (device code).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from hort.credentials.types import CredentialSpec, CredentialType, OAUTH2_PROVIDERS

logger = logging.getLogger(__name__)

# Active OAuth flows (state → flow info)
_pending_flows: dict[str, dict[str, Any]] = {}


def build_auth_url(
    spec: CredentialSpec,
    redirect_uri: str = "http://localhost:8940/auth/callback",
    tenant: str = "",
) -> tuple[str, str]:
    """Build the OAuth2 authorization URL and return (url, state).

    Args:
        spec: The credential spec with provider, scopes, client_id.
        redirect_uri: The redirect URI (must be localhost for security).
        tenant: OAuth tenant (for Microsoft, defaults to "common").

    Returns:
        (auth_url, state) — the URL to redirect the user to, and the
        state parameter for CSRF protection.
    """
    provider_config = OAUTH2_PROVIDERS.get(spec.provider, {})
    auth_url = spec.auth_url or provider_config.get("auth_url", "")
    if not auth_url:
        raise ValueError(f"No auth_url for provider: {spec.provider}")

    # Replace {tenant} placeholder
    effective_tenant = tenant or provider_config.get("default_tenant", "common")
    auth_url = auth_url.replace("{tenant}", effective_tenant)

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": spec.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(spec.scopes),
        "state": state,
        "response_mode": "query",
    }

    # Store pending flow
    _pending_flows[state] = {
        "spec": spec,
        "redirect_uri": redirect_uri,
        "tenant": effective_tenant,
        "created_at": time.time(),
    }

    full_url = f"{auth_url}?{urlencode(params)}"
    return full_url, state


async def exchange_code(
    state: str,
    code: str,
    client_secret: str = "",
) -> dict[str, Any]:
    """Exchange an authorization code for tokens.

    Called by the ``/auth/callback`` handler after the provider redirects
    back with a code.

    Returns the token response dict (access_token, refresh_token, etc.).
    """
    flow = _pending_flows.pop(state, None)
    if not flow:
        raise ValueError("Invalid or expired state parameter")

    spec: CredentialSpec = flow["spec"]
    provider_config = OAUTH2_PROVIDERS.get(spec.provider, {})
    token_url = spec.token_url or provider_config.get("token_url", "")
    if not token_url:
        raise ValueError(f"No token_url for provider: {spec.provider}")

    token_url = token_url.replace("{tenant}", flow["tenant"])

    params = {
        "client_id": spec.client_id,
        "code": code,
        "redirect_uri": flow["redirect_uri"],
        "grant_type": "authorization_code",
    }
    if client_secret:
        params["client_secret"] = client_secret

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=params)
        resp.raise_for_status()
        return resp.json()


async def refresh_token(
    spec: CredentialSpec,
    refresh_token_value: str,
    client_secret: str = "",
    tenant: str = "",
) -> dict[str, Any]:
    """Use a refresh token to get a new access token.

    Returns the new token response dict.
    """
    provider_config = OAUTH2_PROVIDERS.get(spec.provider, {})
    token_url = spec.token_url or provider_config.get("token_url", "")
    if not token_url:
        raise ValueError(f"No token_url for provider: {spec.provider}")

    effective_tenant = tenant or provider_config.get("default_tenant", "common")
    token_url = token_url.replace("{tenant}", effective_tenant)

    params = {
        "client_id": spec.client_id,
        "refresh_token": refresh_token_value,
        "grant_type": "refresh_token",
        "scope": " ".join(spec.scopes),
    }
    if client_secret:
        params["client_secret"] = client_secret

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=params)
        resp.raise_for_status()
        return resp.json()


# ===== Device Code Flow (for remote access) =====


async def start_device_code_flow(
    spec: CredentialSpec,
    tenant: str = "",
) -> dict[str, Any]:
    """Start a device code flow for remote authentication.

    Returns dict with:
    - device_code: internal code (don't show to user)
    - user_code: code the user enters
    - verification_uri: URL the user visits
    - expires_in: seconds until the code expires
    - interval: polling interval in seconds
    """
    provider_config = OAUTH2_PROVIDERS.get(spec.provider, {})
    device_code_url = provider_config.get("device_code_url", "")
    if not device_code_url:
        raise ValueError(f"Device code flow not supported for: {spec.provider}")

    effective_tenant = tenant or provider_config.get("default_tenant", "common")
    device_code_url = device_code_url.replace("{tenant}", effective_tenant)

    params = {
        "client_id": spec.client_id,
        "scope": " ".join(spec.scopes),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(device_code_url, data=params)
        resp.raise_for_status()
        return resp.json()


async def poll_device_code(
    spec: CredentialSpec,
    device_code: str,
    interval: int = 5,
    timeout: int = 300,
    tenant: str = "",
) -> dict[str, Any] | None:
    """Poll for device code completion.

    Blocks until the user completes authentication or timeout.
    Returns the token response, or None on timeout.
    """
    provider_config = OAUTH2_PROVIDERS.get(spec.provider, {})
    token_url = spec.token_url or provider_config.get("token_url", "")
    if not token_url:
        raise ValueError(f"No token_url for provider: {spec.provider}")

    effective_tenant = tenant or provider_config.get("default_tenant", "common")
    token_url = token_url.replace("{tenant}", effective_tenant)

    params = {
        "client_id": spec.client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }

    deadline = time.time() + timeout
    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            resp = await client.post(token_url, data=params)
            data = resp.json()

            if resp.status_code == 200 and "access_token" in data:
                return data

            error = data.get("error", "")
            if error == "authorization_pending":
                await asyncio.sleep(interval)
                continue
            elif error == "slow_down":
                interval += 5
                await asyncio.sleep(interval)
                continue
            elif error in ("authorization_declined", "expired_token", "bad_verification_code"):
                logger.warning("Device code flow failed: %s", error)
                return None
            else:
                logger.warning("Unexpected device code response: %s", data)
                await asyncio.sleep(interval)

    return None  # timeout


# ===== API Key / Bearer Token Validation =====


async def validate_api_key(
    spec: CredentialSpec,
    key: str,
) -> bool:
    """Validate an API key or bearer token against the spec's validate_url.

    Returns True if the endpoint responds with 2xx.
    """
    if not spec.validate_url:
        return True  # no validation URL = assume valid

    headers = {}
    if spec.validate_header:
        headers[spec.validate_header] = f"{spec.validate_header_prefix}{key}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if spec.validate_method.upper() == "GET":
                resp = await client.get(spec.validate_url, headers=headers)
            else:
                resp = await client.post(spec.validate_url, headers=headers)
            return 200 <= resp.status_code < 300
    except Exception:
        return False


async def validate_username_password(
    spec: CredentialSpec,
    username: str,
    password: str,
) -> bool:
    """Validate username/password against the spec's validate_url.

    POSTs JSON {username, password} and checks for 2xx response.
    """
    if not spec.validate_url:
        return True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                spec.validate_url,
                json={"username": username, "password": password},
            )
            return 200 <= resp.status_code < 300
    except Exception:
        return False


# ===== Cleanup =====


def cleanup_expired_flows(max_age: float = 600.0) -> int:
    """Remove pending OAuth flows older than max_age seconds."""
    now = time.time()
    expired = [
        state for state, flow in _pending_flows.items()
        if now - flow["created_at"] > max_age
    ]
    for state in expired:
        del _pending_flows[state]
    return len(expired)
