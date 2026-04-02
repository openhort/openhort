"""Tests for the credential store system — all three auth methods."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hort.ext.credentials import CredentialStore, OAuthConfig


class FakeStore:
    """In-memory PluginStore for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def put(self, key: str, value: dict[str, Any], ttl_seconds: float | None = None) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    async def list_keys(self, prefix: str = "") -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCredentialStore:
    def _make_store(self, oauth: OAuthConfig | None = None) -> tuple[CredentialStore, FakeStore]:
        fake = FakeStore()
        creds = CredentialStore(fake)
        creds.configure(
            provider="microsoft",
            auth_type="oauth2",
            scopes=["Mail.Read"],
            oauth=oauth,
        )
        return creds, fake

    def test_initial_state(self) -> None:
        creds, _ = self._make_store()
        assert creds.state == "not_configured"
        assert not creds.is_authenticated

    def test_set_and_get_token(self) -> None:
        creds, _ = self._make_store()
        _run(creds.set_token(
            token={"access_token": "abc123"},
            account_name="user@example.com",
            expires_at=time.time() + 3600,
        ))
        assert creds.state == "ok"
        assert creds.is_authenticated
        token = _run(creds.get_token())
        assert token is not None
        assert token["access_token"] == "abc123"

    def test_expired_token_detected(self) -> None:
        creds, _ = self._make_store()
        _run(creds.set_token(token={"access_token": "old"}, expires_at=time.time() - 10))
        token = _run(creds.get_token())
        assert token is None
        assert creds.state == "expired"

    def test_mark_expired(self) -> None:
        creds, _ = self._make_store()
        _run(creds.set_token(token={"access_token": "abc123"}))
        _run(creds.mark_expired("API rejected"))
        assert creds.state == "expired"
        assert "rejected" in creds.status_dict()["error_message"]

    def test_clear_logout(self) -> None:
        creds, fake = self._make_store()
        _run(creds.set_token(token={"access_token": "abc123"}, account_name="user"))
        _run(creds.clear())
        assert creds.state == "not_configured"
        assert _run(fake.get("_credentials")) is None

    def test_load_persisted_state(self) -> None:
        creds, fake = self._make_store()
        _run(creds.set_token(token={"access_token": "abc"}, account_name="user@test.com", expires_at=time.time() + 3600))
        creds2 = CredentialStore(fake)
        creds2.configure(provider="microsoft")
        _run(creds2.load())
        assert creds2.state == "ok"
        assert creds2.status_dict()["account_name"] == "user@test.com"

    def test_status_dict_no_secrets(self) -> None:
        creds, _ = self._make_store()
        _run(creds.set_token(token={"access_token": "secret123", "refresh_token": "refresh456"}))
        status = creds.status_dict()
        assert "access_token" not in str(status)
        assert "refresh_token" not in str(status)


class TestSupportedMethods:
    def test_api_key_only(self) -> None:
        creds = CredentialStore(FakeStore())
        creds.configure(provider="test")
        assert creds.status_dict()["supported_methods"] == ["api_key"]

    def test_all_methods(self) -> None:
        creds = CredentialStore(FakeStore())
        creds.configure(
            provider="microsoft",
            oauth=OAuthConfig(
                auth_url="https://example.com/auth",
                token_url="https://example.com/token",
                device_code_url="https://example.com/devicecode",
                client_id="test-client",
            ),
        )
        methods = creds.status_dict()["supported_methods"]
        assert "api_key" in methods
        assert "device_code" in methods
        assert "oauth2" in methods

    def test_oauth_without_device_code(self) -> None:
        creds = CredentialStore(FakeStore())
        creds.configure(
            provider="google",
            oauth=OAuthConfig(
                auth_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
                client_id="test",
            ),
        )
        methods = creds.status_dict()["supported_methods"]
        assert "oauth2" in methods
        assert "device_code" not in methods


class TestOAuthFlow:
    def _make_oauth_store(self) -> CredentialStore:
        creds = CredentialStore(FakeStore())
        creds.configure(
            provider="microsoft",
            oauth=OAuthConfig(
                auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                client_id="test-client-id",
                scopes=["Mail.Read"],
            ),
        )
        return creds

    def test_get_auth_url(self) -> None:
        creds = self._make_oauth_store()
        url = creds.get_auth_url("http://localhost:8940/auth/callback")
        assert url is not None
        assert "client_id=test-client-id" in url
        assert "redirect_uri=" in url
        assert "scope=Mail.Read" in url
        assert "code_challenge=" in url  # PKCE (no client_secret)

    def test_auth_url_none_without_oauth(self) -> None:
        creds = CredentialStore(FakeStore())
        creds.configure(provider="test")
        assert creds.get_auth_url("http://localhost/callback") is None

    def test_validate_state(self) -> None:
        creds = self._make_oauth_store()
        creds.get_auth_url("http://localhost/callback")
        assert creds.validate_state(creds._pending_state)
        assert not creds.validate_state("wrong-state")

    def test_exchange_code_success(self) -> None:
        creds = self._make_oauth_store()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-token",
            "refresh_token": "refresh-123",
            "expires_in": 3600,
            "email": "user@test.com",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            ok = _run(creds.exchange_code("auth-code-123", "http://localhost/callback"))

        assert ok
        assert creds.state == "ok"
        assert creds.status_dict()["account_name"] == "user@test.com"

    def test_exchange_code_failure(self) -> None:
        creds = self._make_oauth_store()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            ok = _run(creds.exchange_code("bad-code", "http://localhost/callback"))

        assert not ok
        assert creds.state == "error"


class TestDeviceCodeFlow:
    def _make_device_store(self) -> CredentialStore:
        creds = CredentialStore(FakeStore())
        creds.configure(
            provider="microsoft",
            oauth=OAuthConfig(
                token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                device_code_url="https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
                client_id="test-client",
                scopes=["Mail.Read"],
            ),
        )
        return creds

    def test_start_device_code(self) -> None:
        creds = self._make_device_store()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "device_code": "device-123",
            "user_code": "ABC-DEF",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "interval": 5,
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = _run(creds.start_device_code())

        assert result is not None
        assert result["user_code"] == "ABC-DEF"
        assert result["verification_uri"] == "https://microsoft.com/devicelogin"

    def test_poll_pending(self) -> None:
        creds = self._make_device_store()
        creds._pending_device_code = "device-123"
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "authorization_pending"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            complete = _run(creds.poll_device_code())

        assert not complete
        assert creds.state == "not_configured"  # Still waiting

    def test_poll_success(self) -> None:
        creds = self._make_device_store()
        creds._pending_device_code = "device-123"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "refresh_token": "refresh-456",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            complete = _run(creds.poll_device_code())

        assert complete
        assert creds.state == "ok"
        assert creds.is_authenticated

    def test_device_code_not_supported(self) -> None:
        creds = CredentialStore(FakeStore())
        creds.configure(provider="test")
        result = _run(creds.start_device_code())
        assert result is None


class TestTokenRefresh:
    def test_auto_refresh_on_expired(self) -> None:
        """Test that _try_refresh is called and works when token is expired."""
        fake = FakeStore()
        creds = CredentialStore(fake)
        creds.configure(
            provider="test",
            oauth=OAuthConfig(
                token_url="https://example.com/token",
                client_id="test",
            ),
        )
        # Store an expired token with a refresh_token
        _run(creds.set_token(
            token={"access_token": "old", "refresh_token": "refresh-abc"},
            expires_at=time.time() - 10,
        ))

        # Mock _try_refresh directly since httpx is imported locally
        refreshed_token = {
            "access_token": "new-token",
            "refresh_token": "refresh-abc",
            "expires_in": 3600,
        }
        creds._try_refresh = AsyncMock(return_value=refreshed_token)
        token = _run(creds.get_token())

        assert token is not None
        assert token["access_token"] == "new-token"
        creds._try_refresh.assert_called_once()

    def test_refresh_failure_marks_expired(self) -> None:
        """When refresh fails, state becomes expired."""
        fake = FakeStore()
        creds = CredentialStore(fake)
        creds.configure(provider="test", oauth=OAuthConfig(token_url="https://example.com/token", client_id="test"))
        _run(creds.set_token(token={"access_token": "old", "refresh_token": "r"}, expires_at=time.time() - 10))

        creds._try_refresh = AsyncMock(return_value=None)
        token = _run(creds.get_token())

        assert token is None
        assert creds.state == "expired"
