"""Credential manager — access control proxy between llmings and the vault.

Each llming gets a scoped ``CredentialAccess`` instance that can only
read/write its own credentials. No llming can access another llming's
secrets. The manager also tracks credential specs (what each llming
needs) and provides the notification/alert system.
"""

from __future__ import annotations

import logging
from typing import Any

from hort.credentials.types import (
    CredentialAlert,
    CredentialInfo,
    CredentialSpec,
    CredentialStatus,
    CredentialType,
)
from hort.credentials.vault import CredentialVault, get_vault

logger = logging.getLogger(__name__)


class CredentialAccess:
    """Scoped credential access for a single llming.

    Injected into the llming instance so it can read/write
    only its own credentials. Cannot access the vault directly.
    """

    def __init__(self, llming_name: str, manager: CredentialManager) -> None:
        self._llming = llming_name
        self._manager = manager

    def get(self, credential_id: str) -> dict[str, Any] | None:
        """Get a decrypted credential value."""
        return self._manager.get(self._llming, credential_id)

    def get_value(self, credential_id: str, key: str = "value") -> str | None:
        """Get a single value from a credential (convenience)."""
        cred = self.get(credential_id)
        if cred is None:
            return None
        return cred.get(key)

    def set(self, credential_id: str, value: dict[str, Any], **kwargs: Any) -> None:
        """Store a credential value."""
        self._manager.set(self._llming, credential_id, value, **kwargs)

    def info(self, credential_id: str) -> CredentialInfo | None:
        """Get credential metadata (no secret values)."""
        return self._manager.info(self._llming, credential_id)

    def list(self) -> list[CredentialInfo]:
        """List all credentials for this llming."""
        return self._manager.list_for_llming(self._llming)

    def request_update(self, credential_id: str, message: str = "") -> None:
        """Signal that a credential needs re-authentication."""
        self._manager.request_update(self._llming, credential_id, message)

    def revoke(self, credential_id: str) -> None:
        """Revoke a credential."""
        self._manager.revoke(self._llming, credential_id)

    @property
    def specs(self) -> list[CredentialSpec]:
        """Get the credential specs for this llming."""
        return self._manager.get_specs(self._llming)


class CredentialManager:
    """Central credential management — enforces access control.

    - Stores credential specs (what each llming needs)
    - Proxies all vault access with llming-scoped permissions
    - Tracks alerts/notifications for expired credentials
    - Provides ``CredentialAccess`` instances for plugin injection
    """

    def __init__(self, vault: CredentialVault | None = None) -> None:
        self._vault = vault or get_vault()
        self._specs: dict[str, list[CredentialSpec]] = {}  # llming_name -> specs
        self._alerts: list[CredentialAlert] = []

    def register_specs(self, llming_name: str, specs: list[CredentialSpec]) -> None:
        """Register credential specs for a llming (from manifest/config)."""
        self._specs[llming_name] = specs

    def get_specs(self, llming_name: str) -> list[CredentialSpec]:
        """Get credential specs for a llming."""
        return self._specs.get(llming_name, [])

    def get_access(self, llming_name: str) -> CredentialAccess:
        """Create a scoped access proxy for a llming."""
        return CredentialAccess(llming_name, self)

    # ── Proxied vault operations ───────────────────────────────────

    def get(self, llming_name: str, credential_id: str) -> dict[str, Any] | None:
        """Get a decrypted credential value for a specific llming."""
        return self._vault.retrieve(llming_name, credential_id)

    def set(
        self,
        llming_name: str,
        credential_id: str,
        value: dict[str, Any],
        *,
        credential_type: CredentialType | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a credential for a specific llming."""
        # Determine type from specs if not provided
        if credential_type is None:
            specs = self._specs.get(llming_name, [])
            for spec in specs:
                if spec.id == credential_id:
                    credential_type = spec.type
                    break
            if credential_type is None:
                credential_type = CredentialType.API_KEY

        self._vault.store(
            llming_name, credential_id, credential_type,
            value, expires_at=expires_at, metadata=metadata,
        )
        # Clear any alerts for this credential
        self._alerts = [
            a for a in self._alerts
            if not (a.llming_name == llming_name and a.credential_id == credential_id)
        ]

    def info(self, llming_name: str, credential_id: str) -> CredentialInfo | None:
        """Get credential metadata (no secret values)."""
        return self._vault.get_info(llming_name, credential_id)

    def list_for_llming(self, llming_name: str) -> list[CredentialInfo]:
        """List all stored credentials for a llming."""
        return self._vault.list_for_llming(llming_name)

    def list_all(self) -> list[CredentialInfo]:
        """List all stored credentials."""
        return self._vault.list_all()

    def revoke(self, llming_name: str, credential_id: str) -> None:
        """Revoke a credential."""
        self._vault.revoke(llming_name, credential_id)

    # ── Status & alerts ────────────────────────────────────────────

    def request_update(
        self, llming_name: str, credential_id: str, message: str = "",
    ) -> None:
        """Signal that a credential needs re-authentication."""
        # Find spec for label
        label = credential_id
        for spec in self._specs.get(llming_name, []):
            if spec.id == credential_id:
                label = spec.label or credential_id
                break

        self._vault.update_status(
            llming_name, credential_id, CredentialStatus.EXPIRED,
        )

        alert = CredentialAlert(
            llming_name=llming_name,
            credential_id=credential_id,
            label=label,
            status=CredentialStatus.EXPIRED,
            message=message or f"{label} needs re-authentication",
        )
        # Deduplicate
        self._alerts = [
            a for a in self._alerts
            if not (a.llming_name == llming_name and a.credential_id == credential_id)
        ]
        self._alerts.append(alert)
        logger.warning(
            "Credential alert: %s:%s — %s", llming_name, credential_id, message,
        )

    def get_alerts(self) -> list[CredentialAlert]:
        """Get all active credential alerts."""
        return list(self._alerts)

    def clear_alert(self, llming_name: str, credential_id: str) -> None:
        """Clear an alert (after re-authentication)."""
        self._alerts = [
            a for a in self._alerts
            if not (a.llming_name == llming_name and a.credential_id == credential_id)
        ]

    # ── Unconfigured check ─────────────────────────────────────────

    def get_unconfigured(self) -> list[tuple[str, CredentialSpec]]:
        """List all required credentials that haven't been set up yet."""
        unconfigured = []
        for llming_name, specs in self._specs.items():
            for spec in specs:
                if not spec.required:
                    continue
                info = self._vault.get_info(llming_name, spec.id)
                if info is None or info.status in (
                    CredentialStatus.UNCONFIGURED,
                    CredentialStatus.REVOKED,
                ):
                    unconfigured.append((llming_name, spec))
        return unconfigured


# ===== Singleton =====

_manager: CredentialManager | None = None


def get_credential_manager() -> CredentialManager:
    """Get the global credential manager (singleton)."""
    global _manager
    if _manager is None:
        _manager = CredentialManager()
    return _manager


def reset_credential_manager() -> None:
    """Reset the singleton (for testing)."""
    global _manager
    _manager = None
