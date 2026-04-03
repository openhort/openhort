"""Credential store — shared auth framework for Llmings.

Supports three authentication methods:

1. **API token** — user pastes a token from the service's settings page.
   Simplest, works everywhere. No callback URL needed.

2. **Device code** — system requests a code from the provider, user enters
   it on the provider's website. No callback URL needed. Great for
   mobile and headless setups.

3. **OAuth 2.0 callback** — full browser redirect flow. Best UX on desktop.
   Requires a reachable callback URL (works via cloud proxy for remote access).

Auth states:
- ``ok`` — valid credentials, service is accessible
- ``expired`` — credentials exist but need refresh/re-login
- ``not_configured`` — no credentials stored (first-time setup)
- ``error`` — auth failed for an unexpected reason

When a Llming's auth expires, it calls ``mark_expired()`` which
makes the state visible in the grid UI (warning icon) and to the
chat backend (powers become temporarily unavailable).

Usage::

    class Office365(PluginBase, MCPMixin):
        def activate(self, config):
            self.creds = CredentialStore(self.store, self.log)
            self.creds.configure(
                provider="microsoft",
                auth_type="oauth2",
                scopes=["Mail.Read", "Calendar.Read"],
                oauth=OAuthConfig(
                    auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                    token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                    device_code_url="https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
                    client_id=config.get("client_id", ""),
                ),
            )
"""

from __future__ import annotations

import logging
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Literal

AuthState = Literal["ok", "expired", "not_configured", "error"]


@dataclass
class OAuthConfig:
    """OAuth 2.0 / device code configuration for a provider."""

    auth_url: str = ""  # Authorization endpoint
    token_url: str = ""  # Token exchange endpoint
    device_code_url: str = ""  # Device code endpoint (optional)
    client_id: str = ""
    client_secret: str = ""  # Empty = public client (PKCE)
    scopes: list[str] = field(default_factory=list)


@dataclass
class CredentialInfo:
    """Non-secret auth metadata exposed to the UI."""

    state: AuthState = "not_configured"
    provider: str = ""
    auth_type: str = ""  # "oauth2", "api_key", "device_code"
    account_name: str = ""
    scopes: list[str] = field(default_factory=list)
    expires_at: float = 0.0
    error_message: str = ""
    last_refreshed: float = 0.0
    # Auth methods this provider supports
    supported_methods: list[str] = field(default_factory=list)


class CredentialStore:
    """Per-Llming credential management with OAuth, device code, and API token support."""

    _CRED_KEY = "_credentials"
    _META_KEY = "_credential_meta"

    def __init__(
        self,
        store: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._log = logger or logging.getLogger(__name__)
        self._info = CredentialInfo()
        self._oauth: OAuthConfig | None = None
        self._loaded = False
        self._pending_state: str = ""  # CSRF state for OAuth
        self._pending_device_code: str = ""
        self._pending_device_interval: int = 5

    def configure(
        self,
        provider: str,
        auth_type: str = "oauth2",
        scopes: list[str] | None = None,
        oauth: OAuthConfig | None = None,
    ) -> None:
        """Declare what auth this Llming needs."""
        self._info.provider = provider
        self._info.auth_type = auth_type
        self._info.scopes = scopes or (oauth.scopes if oauth else [])
        self._oauth = oauth

        # Determine supported methods
        methods = ["api_key"]  # Always available
        if oauth:
            if oauth.device_code_url:
                methods.append("device_code")
            if oauth.auth_url and oauth.token_url:
                methods.append("oauth2")
        self._info.supported_methods = methods

    async def load(self) -> None:
        """Load persisted credential state from store."""
        meta = await self._store.get(self._META_KEY)
        if meta:
            self._info.state = meta.get("state", "not_configured")
            self._info.account_name = meta.get("account_name", "")
            self._info.expires_at = meta.get("expires_at", 0.0)
            self._info.last_refreshed = meta.get("last_refreshed", 0.0)
            self._info.error_message = meta.get("error_message", "")
            if self._info.state == "ok" and self._info.expires_at:
                if self._info.expires_at < time.time():
                    self._info.state = "expired"
        else:
            self._info.state = "not_configured"
        self._loaded = True

    # ── Token access ──────────────────────────────────────────────

    async def get_token(self) -> dict[str, Any] | None:
        """Get the stored credential. Returns None if not available."""
        if not self._loaded:
            await self.load()

        if self._info.state != "ok":
            return None

        cred = await self._store.get(self._CRED_KEY)
        if not cred:
            self._info.state = "not_configured"
            return None

        expires_at = cred.get("expires_at", 0)
        if expires_at and expires_at < time.time():
            # Try refresh before giving up
            refreshed = await self._try_refresh(cred)
            if refreshed:
                return refreshed
            self._info.state = "expired"
            await self._save_meta()
            return None

        return cred

    async def set_token(
        self,
        token: dict[str, Any],
        account_name: str = "",
        expires_at: float = 0.0,
    ) -> None:
        """Store a new credential/token."""
        if expires_at:
            token["expires_at"] = expires_at
        await self._store.put(self._CRED_KEY, token)
        self._info.state = "ok"
        self._info.account_name = account_name or token.get("account_name", "")
        self._info.expires_at = expires_at
        self._info.last_refreshed = time.time()
        self._info.error_message = ""
        self._loaded = True
        await self._save_meta()
        self._log.info("Credential stored for %s (%s)", self._info.provider, self._info.account_name)

    async def mark_expired(self, message: str = "") -> None:
        """Mark the credential as expired (needs re-login)."""
        self._info.state = "expired"
        self._info.error_message = message or "Token expired — re-login required"
        await self._save_meta()
        self._log.warning("Credential expired: %s", self._info.error_message)

    async def mark_error(self, message: str) -> None:
        """Mark an auth error."""
        self._info.state = "error"
        self._info.error_message = message
        await self._save_meta()

    async def clear(self) -> None:
        """Remove all stored credentials (logout)."""
        await self._store.delete(self._CRED_KEY)
        self._info.state = "not_configured"
        self._info.account_name = ""
        self._info.expires_at = 0.0
        self._info.error_message = ""
        await self._save_meta()
        self._log.info("Credential cleared for %s", self._info.provider)

    @property
    def state(self) -> AuthState:
        return self._info.state

    @property
    def is_authenticated(self) -> bool:
        return self._info.state == "ok"

    def status_dict(self) -> dict[str, Any]:
        """Auth status for the API (no secrets)."""
        return {
            "state": self._info.state,
            "provider": self._info.provider,
            "auth_type": self._info.auth_type,
            "account_name": self._info.account_name,
            "scopes": self._info.scopes,
            "expires_at": self._info.expires_at,
            "error_message": self._info.error_message,
            "last_refreshed": self._info.last_refreshed,
            "supported_methods": self._info.supported_methods,
        }

    # ── OAuth 2.0 browser flow ────────────────────────────────────

    def get_auth_url(self, redirect_uri: str) -> str | None:
        """Build the OAuth 2.0 authorization URL for browser redirect.

        Returns the URL the user should be redirected to, or None if
        OAuth is not configured.
        """
        if not self._oauth or not self._oauth.auth_url:
            return None

        self._pending_state = secrets.token_urlsafe(32)

        params = {
            "client_id": self._oauth.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(self._oauth.scopes or self._info.scopes),
            "state": self._pending_state,
        }
        # PKCE for public clients
        if not self._oauth.client_secret:
            import hashlib
            import base64
            self._code_verifier = secrets.token_urlsafe(64)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(self._code_verifier.encode()).digest()
            ).rstrip(b"=").decode()
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        return f"{self._oauth.auth_url}?{urllib.parse.urlencode(params)}"

    def validate_state(self, state: str) -> bool:
        """Validate the OAuth state parameter (CSRF protection)."""
        return bool(self._pending_state and state == self._pending_state)

    async def exchange_code(self, code: str, redirect_uri: str) -> bool:
        """Exchange an OAuth authorization code for tokens.

        Returns True on success, False on failure.
        """
        if not self._oauth or not self._oauth.token_url:
            return False

        import httpx

        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self._oauth.client_id,
        }
        if self._oauth.client_secret:
            data["client_secret"] = self._oauth.client_secret
        if hasattr(self, "_code_verifier"):
            data["code_verifier"] = self._code_verifier

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._oauth.token_url, data=data)
                if resp.status_code != 200:
                    self._log.error("Token exchange failed: %s %s", resp.status_code, resp.text[:200])
                    await self.mark_error(f"Token exchange failed: {resp.status_code}")
                    return False
                token_data = resp.json()
        except Exception as exc:
            await self.mark_error(f"Token exchange error: {exc}")
            return False

        expires_in = token_data.get("expires_in", 0)
        expires_at = time.time() + expires_in if expires_in else 0.0

        await self.set_token(
            token=token_data,
            account_name=token_data.get("email", token_data.get("name", "")),
            expires_at=expires_at,
        )
        self._pending_state = ""
        return True

    # ── Device code flow ──────────────────────────────────────────

    async def start_device_code(self) -> dict[str, str] | None:
        """Request a device code from the provider.

        Returns ``{"user_code": "ABC-123", "verification_uri": "https://..."}``
        or None if device code flow is not configured.
        """
        if not self._oauth or not self._oauth.device_code_url:
            return None

        import httpx

        data = {
            "client_id": self._oauth.client_id,
            "scope": " ".join(self._oauth.scopes or self._info.scopes),
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._oauth.device_code_url, data=data)
                if resp.status_code != 200:
                    self._log.error("Device code request failed: %s", resp.status_code)
                    return None
                result = resp.json()
        except Exception as exc:
            self._log.error("Device code request error: %s", exc)
            return None

        self._pending_device_code = result.get("device_code", "")
        self._pending_device_interval = result.get("interval", 5)

        return {
            "user_code": result.get("user_code", ""),
            "verification_uri": result.get("verification_uri", result.get("verification_url", "")),
            "expires_in": result.get("expires_in", 900),
            "interval": self._pending_device_interval,
        }

    async def poll_device_code(self) -> bool:
        """Poll for device code completion. Returns True when auth succeeds.

        Call this periodically (every ``interval`` seconds) after
        ``start_device_code()``. Returns False if still pending,
        True if complete, or raises on error.
        """
        if not self._oauth or not self._oauth.token_url or not self._pending_device_code:
            return False

        import httpx

        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self._oauth.client_id,
            "device_code": self._pending_device_code,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._oauth.token_url, data=data)
                result = resp.json()
        except Exception:
            return False

        error = result.get("error")
        if error == "authorization_pending":
            return False
        if error == "slow_down":
            self._pending_device_interval += 5
            return False
        if error:
            await self.mark_error(f"Device code error: {error}")
            self._pending_device_code = ""
            return False

        # Success
        expires_in = result.get("expires_in", 0)
        expires_at = time.time() + expires_in if expires_in else 0.0

        await self.set_token(
            token=result,
            account_name=result.get("email", result.get("name", "")),
            expires_at=expires_at,
        )
        self._pending_device_code = ""
        return True

    # ── Token refresh ─────────────────────────────────────────────

    async def _try_refresh(self, cred: dict[str, Any]) -> dict[str, Any] | None:
        """Try to refresh an expired token using the refresh_token."""
        refresh_token = cred.get("refresh_token")
        if not refresh_token or not self._oauth or not self._oauth.token_url:
            return None

        import httpx

        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._oauth.client_id,
        }
        if self._oauth.client_secret:
            data["client_secret"] = self._oauth.client_secret

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._oauth.token_url, data=data)
                if resp.status_code != 200:
                    self._log.warning("Token refresh failed: %s", resp.status_code)
                    return None
                token_data = resp.json()
        except Exception as exc:
            self._log.warning("Token refresh error: %s", exc)
            return None

        # Preserve refresh_token if not included in response
        if "refresh_token" not in token_data:
            token_data["refresh_token"] = refresh_token

        expires_in = token_data.get("expires_in", 0)
        expires_at = time.time() + expires_in if expires_in else 0.0

        await self.set_token(
            token=token_data,
            account_name=self._info.account_name,
            expires_at=expires_at,
        )
        self._log.info("Token refreshed for %s", self._info.provider)
        return token_data

    async def _save_meta(self) -> None:
        """Persist non-secret metadata."""
        await self._store.put(self._META_KEY, {
            "state": self._info.state,
            "account_name": self._info.account_name,
            "expires_at": self._info.expires_at,
            "last_refreshed": self._info.last_refreshed,
            "error_message": self._info.error_message,
        })
