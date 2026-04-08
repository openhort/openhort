"""Tests for CredentialVault — encrypted storage."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hort.credentials.types import CredentialStatus, CredentialType
from hort.credentials.vault import CredentialVault


@pytest.fixture
def vault(tmp_path):
    """Create a vault with a temp database."""
    db = tmp_path / "test-vault.db"
    # Force file-based key (no OS keychain in tests)
    key_file = tmp_path / "vault.key"
    key_file.write_text("test-secret-key-for-unit-tests")
    key_file.chmod(0o600)

    # Patch the key file path
    import hort.credentials.vault as v
    original_key_file = v.VAULT_KEY_FILE
    v.VAULT_KEY_FILE = key_file
    vault = CredentialVault(db_path=db)
    yield vault
    v.VAULT_KEY_FILE = original_key_file


def test_store_and_retrieve(vault):
    vault.store("my-llming", "api_key", CredentialType.API_KEY, {"value": "sk-test-123"})
    result = vault.retrieve("my-llming", "api_key")
    assert result == {"value": "sk-test-123"}


def test_retrieve_nonexistent(vault):
    result = vault.retrieve("no-such", "no-such")
    assert result is None


def test_store_overwrites(vault):
    vault.store("llm", "key", CredentialType.API_KEY, {"value": "old"})
    vault.store("llm", "key", CredentialType.API_KEY, {"value": "new"})
    result = vault.retrieve("llm", "key")
    assert result == {"value": "new"}


def test_get_info(vault):
    vault.store(
        "email", "oauth", CredentialType.OAUTH2, {"access_token": "tok"},
        metadata={"provider": "microsoft", "scopes": ["Mail.Read"], "label": "Work Email"},
    )
    info = vault.get_info("email", "oauth")
    assert info is not None
    assert info.credential_type == CredentialType.OAUTH2
    assert info.status == CredentialStatus.VALID
    assert info.provider == "microsoft"
    assert info.scopes == ["Mail.Read"]
    assert info.label == "Work Email"


def test_list_for_llming(vault):
    vault.store("llm-a", "key1", CredentialType.API_KEY, {"v": "1"})
    vault.store("llm-a", "key2", CredentialType.BEARER_TOKEN, {"v": "2"})
    vault.store("llm-b", "key1", CredentialType.API_KEY, {"v": "3"})

    results = vault.list_for_llming("llm-a")
    assert len(results) == 2
    assert {r.credential_id for r in results} == {"key1", "key2"}


def test_list_all(vault):
    vault.store("a", "k1", CredentialType.API_KEY, {"v": "1"})
    vault.store("b", "k2", CredentialType.API_KEY, {"v": "2"})
    results = vault.list_all()
    assert len(results) == 2


def test_revoke(vault):
    vault.store("llm", "key", CredentialType.API_KEY, {"value": "secret"})
    vault.revoke("llm", "key")

    # Retrieve returns None for revoked
    assert vault.retrieve("llm", "key") is None

    # Info shows revoked status
    info = vault.get_info("llm", "key")
    assert info.status == CredentialStatus.REVOKED


def test_delete(vault):
    vault.store("llm", "key", CredentialType.API_KEY, {"value": "secret"})
    vault.delete("llm", "key")
    assert vault.get_info("llm", "key") is None


def test_update_status(vault):
    vault.store("llm", "key", CredentialType.API_KEY, {"value": "x"})
    vault.update_status("llm", "key", CredentialStatus.EXPIRED)
    info = vault.get_info("llm", "key")
    assert info.status == CredentialStatus.EXPIRED


def test_list_expired(vault):
    vault.store("a", "k1", CredentialType.API_KEY, {"v": "1"})
    vault.store("b", "k2", CredentialType.API_KEY, {"v": "2"})
    vault.update_status("b", "k2", CredentialStatus.EXPIRED)

    expired = vault.list_expired()
    assert len(expired) == 1
    assert expired[0].llming_name == "b"


def test_store_with_expiry(vault):
    vault.store(
        "llm", "tok", CredentialType.OAUTH2,
        {"access_token": "x"}, expires_at="2026-12-31T23:59:59Z",
    )
    info = vault.get_info("llm", "tok")
    assert info.expires_at == "2026-12-31T23:59:59Z"


def test_isolation_between_llmings(vault):
    """One llming's credentials are invisible to another."""
    vault.store("llm-a", "secret", CredentialType.API_KEY, {"value": "a-secret"})
    vault.store("llm-b", "secret", CredentialType.API_KEY, {"value": "b-secret"})

    assert vault.retrieve("llm-a", "secret") == {"value": "a-secret"}
    assert vault.retrieve("llm-b", "secret") == {"value": "b-secret"}
    assert vault.list_for_llming("llm-a")[0].llming_name == "llm-a"
