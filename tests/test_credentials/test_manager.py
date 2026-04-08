"""Tests for CredentialManager — access control proxy."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hort.credentials.manager import CredentialAccess, CredentialManager
from hort.credentials.types import (
    CredentialSpec,
    CredentialStatus,
    CredentialType,
)
from hort.credentials.vault import CredentialVault


@pytest.fixture
def vault(tmp_path):
    key_file = tmp_path / "vault.key"
    key_file.write_text("test-key")
    key_file.chmod(0o600)

    import hort.credentials.vault as v
    original = v.VAULT_KEY_FILE
    v.VAULT_KEY_FILE = key_file
    vault = CredentialVault(db_path=tmp_path / "test.db")
    yield vault
    v.VAULT_KEY_FILE = original


@pytest.fixture
def manager(vault):
    return CredentialManager(vault=vault)


def test_scoped_access_store_and_retrieve(manager):
    access = manager.get_access("my-llming")
    access.set("api_key", {"value": "sk-test"})
    result = access.get("api_key")
    assert result == {"value": "sk-test"}


def test_scoped_access_get_value(manager):
    access = manager.get_access("llm")
    access.set("key", {"value": "secret", "extra": "data"})
    assert access.get_value("key", "value") == "secret"
    assert access.get_value("key", "extra") == "data"
    assert access.get_value("nonexistent") is None


def test_scoped_access_isolation(manager):
    """LlmingA cannot access LlmingB's credentials."""
    access_a = manager.get_access("llming-a")
    access_b = manager.get_access("llming-b")

    access_a.set("secret", {"value": "a-value"})
    access_b.set("secret", {"value": "b-value"})

    assert access_a.get("secret") == {"value": "a-value"}
    assert access_b.get("secret") == {"value": "b-value"}

    # A can't read B's (different llming_name scoping)
    assert access_a.get_value("secret") == "a-value"


def test_register_and_get_specs(manager):
    specs = [
        CredentialSpec(id="oauth", type=CredentialType.OAUTH2, label="Microsoft"),
        CredentialSpec(id="api", type=CredentialType.API_KEY, label="API Key"),
    ]
    manager.register_specs("email", specs)

    access = manager.get_access("email")
    assert len(access.specs) == 2
    assert access.specs[0].id == "oauth"


def test_request_update_creates_alert(manager):
    manager.register_specs("email", [
        CredentialSpec(id="oauth", type=CredentialType.OAUTH2, label="Work Email"),
    ])

    access = manager.get_access("email")
    # First store a credential
    access.set("oauth", {"access_token": "old"})
    # Then request update
    access.request_update("oauth", "Token expired")

    alerts = manager.get_alerts()
    assert len(alerts) == 1
    assert alerts[0].llming_name == "email"
    assert alerts[0].credential_id == "oauth"
    assert "expired" in alerts[0].message.lower()


def test_storing_clears_alert(manager):
    manager.register_specs("llm", [
        CredentialSpec(id="key", type=CredentialType.API_KEY, label="API Key"),
    ])
    access = manager.get_access("llm")
    access.set("key", {"value": "old"})
    access.request_update("key", "Invalid key")

    assert len(manager.get_alerts()) == 1

    # Re-set clears the alert
    access.set("key", {"value": "new-valid-key"})
    assert len(manager.get_alerts()) == 0


def test_revoke(manager):
    access = manager.get_access("llm")
    access.set("key", {"value": "secret"})
    access.revoke("key")
    assert access.get("key") is None


def test_get_unconfigured(manager):
    manager.register_specs("email", [
        CredentialSpec(id="oauth", type=CredentialType.OAUTH2, required=True),
        CredentialSpec(id="optional", type=CredentialType.API_KEY, required=False),
    ])
    manager.register_specs("chat", [
        CredentialSpec(id="api_key", type=CredentialType.API_KEY, required=True),
    ])

    # Nothing configured yet
    unconfigured = manager.get_unconfigured()
    assert len(unconfigured) == 2  # oauth + api_key (not optional)

    # Configure one
    manager.set("email", "oauth", {"token": "x"}, credential_type=CredentialType.OAUTH2)
    unconfigured = manager.get_unconfigured()
    assert len(unconfigured) == 1
    assert unconfigured[0][1].id == "api_key"


def test_list_all(manager):
    manager.set("a", "k1", {"v": "1"}, credential_type=CredentialType.API_KEY)
    manager.set("b", "k2", {"v": "2"}, credential_type=CredentialType.API_KEY)
    all_creds = manager.list_all()
    assert len(all_creds) == 2
