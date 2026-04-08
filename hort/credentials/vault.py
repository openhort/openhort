"""Encrypted credential vault — SQLite + Fernet.

Stores credential values encrypted at rest. The master encryption key
is derived from a random secret stored in the OS keychain (macOS
Keychain, Linux libsecret, Windows Credential Manager). If the OS
keychain is unavailable, falls back to a file-based key at
``~/.openhort/vault.key`` (chmod 600).

No llming accesses this directly — all access goes through
:class:`~hort.credentials.manager.CredentialManager`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import secrets
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from hort.credentials.types import CredentialInfo, CredentialStatus, CredentialType

logger = logging.getLogger(__name__)

DEFAULT_VAULT_PATH = Path.home() / ".openhort" / "vault.db"
VAULT_KEY_SERVICE = "openhort-vault-key"
VAULT_KEY_FILE = Path.home() / ".openhort" / "vault.key"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
    id TEXT PRIMARY KEY,
    llming_name TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    credential_type TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT DEFAULT 'valid',
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_llming ON credentials(llming_name);
CREATE INDEX IF NOT EXISTS idx_status ON credentials(status);
"""


class CredentialVault:
    """Encrypted credential storage backed by SQLite."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or DEFAULT_VAULT_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._get_or_create_key())
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    # ── CRUD ───────────────────────────────────────────────────────

    def store(
        self,
        llming_name: str,
        credential_id: str,
        credential_type: CredentialType,
        value: dict[str, Any],
        *,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Encrypt and store a credential."""
        row_id = f"{llming_name}:{credential_id}"
        now = datetime.now(timezone.utc).isoformat()
        encrypted = self._fernet.encrypt(json.dumps(value).encode())

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO credentials
                   (id, llming_name, credential_id, credential_type,
                    encrypted_value, created_at, updated_at, expires_at, status, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'valid', ?)
                   ON CONFLICT(id) DO UPDATE SET
                    encrypted_value=excluded.encrypted_value,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at,
                    status='valid',
                    metadata=excluded.metadata
                """,
                (row_id, llming_name, credential_id, credential_type.value,
                 encrypted, now, now, expires_at,
                 json.dumps(metadata) if metadata else None),
            )
        logger.info("Stored credential %s:%s", llming_name, credential_id)

    def retrieve(self, llming_name: str, credential_id: str) -> dict[str, Any] | None:
        """Decrypt and return a credential value, or None if not found."""
        row_id = f"{llming_name}:{credential_id}"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT encrypted_value, status FROM credentials WHERE id = ?",
                (row_id,),
            ).fetchone()
        if not row:
            return None
        if row[1] == CredentialStatus.REVOKED.value:
            return None
        try:
            decrypted = self._fernet.decrypt(row[0])
            return json.loads(decrypted)
        except Exception:
            logger.warning("Failed to decrypt credential %s", row_id)
            return None

    def get_info(self, llming_name: str, credential_id: str) -> CredentialInfo | None:
        """Get credential metadata (no decryption)."""
        row_id = f"{llming_name}:{credential_id}"
        with self._connect() as conn:
            row = conn.execute(
                """SELECT llming_name, credential_id, credential_type,
                          status, created_at, updated_at, expires_at, metadata
                   FROM credentials WHERE id = ?""",
                (row_id,),
            ).fetchone()
        if not row:
            return None
        meta = json.loads(row[7]) if row[7] else {}
        return CredentialInfo(
            llming_name=row[0],
            credential_id=row[1],
            credential_type=CredentialType(row[2]),
            status=CredentialStatus(row[3]),
            label=meta.get("label", ""),
            created_at=row[4],
            updated_at=row[5],
            expires_at=row[6],
            provider=meta.get("provider", ""),
            scopes=meta.get("scopes", []),
            remote_update=meta.get("remote_update", False),
        )

    def list_for_llming(self, llming_name: str) -> list[CredentialInfo]:
        """List all credentials for a llming (no decryption)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT llming_name, credential_id, credential_type,
                          status, created_at, updated_at, expires_at, metadata
                   FROM credentials WHERE llming_name = ?
                   ORDER BY credential_id""",
                (llming_name,),
            ).fetchall()
        results = []
        for row in rows:
            meta = json.loads(row[7]) if row[7] else {}
            results.append(CredentialInfo(
                llming_name=row[0],
                credential_id=row[1],
                credential_type=CredentialType(row[2]),
                status=CredentialStatus(row[3]),
                label=meta.get("label", ""),
                created_at=row[4],
                updated_at=row[5],
                expires_at=row[6],
                provider=meta.get("provider", ""),
                scopes=meta.get("scopes", []),
                remote_update=meta.get("remote_update", False),
            ))
        return results

    def list_all(self) -> list[CredentialInfo]:
        """List all stored credentials (no decryption)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT llming_name, credential_id, credential_type,
                          status, created_at, updated_at, expires_at, metadata
                   FROM credentials ORDER BY llming_name, credential_id""",
            ).fetchall()
        results = []
        for row in rows:
            meta = json.loads(row[7]) if row[7] else {}
            results.append(CredentialInfo(
                llming_name=row[0],
                credential_id=row[1],
                credential_type=CredentialType(row[2]),
                status=CredentialStatus(row[3]),
                label=meta.get("label", ""),
                created_at=row[4],
                updated_at=row[5],
                expires_at=row[6],
                provider=meta.get("provider", ""),
                scopes=meta.get("scopes", []),
                remote_update=meta.get("remote_update", False),
            ))
        return results

    def list_expired(self) -> list[CredentialInfo]:
        """List credentials with expired or error status."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT llming_name, credential_id, credential_type,
                          status, created_at, updated_at, expires_at, metadata
                   FROM credentials
                   WHERE status IN ('expired', 'expiring', 'error')
                   ORDER BY updated_at""",
            ).fetchall()
        results = []
        for row in rows:
            meta = json.loads(row[7]) if row[7] else {}
            results.append(CredentialInfo(
                llming_name=row[0],
                credential_id=row[1],
                credential_type=CredentialType(row[2]),
                status=CredentialStatus(row[3]),
                label=meta.get("label", ""),
                created_at=row[4],
                updated_at=row[5],
                expires_at=row[6],
                provider=meta.get("provider", ""),
                scopes=meta.get("scopes", []),
                remote_update=meta.get("remote_update", False),
            ))
        return results

    def update_status(
        self, llming_name: str, credential_id: str, status: CredentialStatus,
    ) -> None:
        """Update the status of a credential."""
        row_id = f"{llming_name}:{credential_id}"
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE credentials SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, row_id),
            )

    def revoke(self, llming_name: str, credential_id: str) -> None:
        """Mark as revoked and clear the encrypted value."""
        row_id = f"{llming_name}:{credential_id}"
        now = datetime.now(timezone.utc).isoformat()
        # Overwrite with empty encrypted blob
        empty = self._fernet.encrypt(b'{}')
        with self._connect() as conn:
            conn.execute(
                """UPDATE credentials
                   SET status = 'revoked', encrypted_value = ?, updated_at = ?
                   WHERE id = ?""",
                (empty, now, row_id),
            )
        logger.info("Revoked credential %s:%s", llming_name, credential_id)

    def delete(self, llming_name: str, credential_id: str) -> None:
        """Permanently delete a credential."""
        row_id = f"{llming_name}:{credential_id}"
        with self._connect() as conn:
            conn.execute("DELETE FROM credentials WHERE id = ?", (row_id,))
        logger.info("Deleted credential %s:%s", llming_name, credential_id)

    # ── Encryption key management ──────────────────────────────────

    def _get_or_create_key(self) -> bytes:
        """Get the Fernet key from OS keychain, or create one.

        Falls back to file-based key if keychain is unavailable.
        """
        # Try OS keychain first
        try:
            raw = self._read_keychain()
            if raw:
                return self._derive_fernet_key(raw)
        except Exception:
            pass

        # Try file-based key
        if VAULT_KEY_FILE.exists():
            raw = VAULT_KEY_FILE.read_text().strip()
            return self._derive_fernet_key(raw)

        # Generate new key
        raw = secrets.token_hex(32)

        # Try to store in OS keychain
        try:
            self._write_keychain(raw)
            logger.info("Vault key stored in OS keychain")
        except Exception:
            # Fall back to file
            VAULT_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            VAULT_KEY_FILE.write_text(raw)
            VAULT_KEY_FILE.chmod(0o600)
            logger.info("Vault key stored in file (chmod 600)")

        return self._derive_fernet_key(raw)

    @staticmethod
    def _derive_fernet_key(raw: str) -> bytes:
        """Derive a Fernet-compatible key from a raw secret."""
        # PBKDF2 with fixed salt (vault is local, not shared)
        dk = hashlib.pbkdf2_hmac(
            "sha256", raw.encode(), b"openhort-vault-v1", 100_000, dklen=32,
        )
        return base64.urlsafe_b64encode(dk)

    @staticmethod
    def _read_keychain() -> str | None:
        """Read vault key from OS keychain."""
        system = platform.system()
        try:
            if system == "Darwin":
                return subprocess.check_output(
                    ["security", "find-generic-password",
                     "-s", VAULT_KEY_SERVICE, "-w"],
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()
            elif system == "Linux":
                return subprocess.check_output(
                    ["secret-tool", "lookup", "service", VAULT_KEY_SERVICE],
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return None

    @staticmethod
    def _write_keychain(value: str) -> None:
        """Write vault key to OS keychain."""
        system = platform.system()
        if system == "Darwin":
            subprocess.run(
                ["security", "add-generic-password",
                 "-s", VAULT_KEY_SERVICE,
                 "-a", "openhort",
                 "-w", value,
                 "-U"],  # update if exists
                check=True, stderr=subprocess.DEVNULL,
            )
        elif system == "Linux":
            subprocess.run(
                ["secret-tool", "store",
                 "--label", "openhort vault key",
                 "service", VAULT_KEY_SERVICE],
                input=value.encode(), check=True,
                stderr=subprocess.DEVNULL,
            )


# ===== Singleton =====

_vault: CredentialVault | None = None


def get_vault() -> CredentialVault:
    """Get the global credential vault (singleton)."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault


def reset_vault() -> None:
    """Reset the singleton (for testing)."""
    global _vault
    _vault = None
