"""Credential resolution — env:, vault:, file: prefixes.

Resolves credential references to actual values at startup.
Secrets are never logged or serialized — they flow directly
into ``SessionConfig.secret_env`` for per-process injection.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("hort.wiring.credentials")


def resolve_credential(ref: str) -> str:
    """Resolve a credential reference to its value.

    Supported schemes:
    - ``env:VAR_NAME`` — environment variable
    - ``vault:path/key`` — credential vault (file-based stub)
    - ``file:/path/to/secret`` — read from file (first line)
    - plain string — returned as-is

    Raises:
        ValueError: If the reference cannot be resolved.
    """
    if ref.startswith("env:"):
        var_name = ref[4:]
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(f"Environment variable not set: {var_name}")
        return value

    if ref.startswith("vault:"):
        vault_path = ref[6:]
        return _resolve_vault(vault_path)

    if ref.startswith("file:"):
        file_path = ref[5:]
        return _resolve_file(file_path)

    # Plain string — used as-is (log a warning for secrets)
    return ref


def resolve_credentials(creds: dict[str, str]) -> dict[str, str]:
    """Resolve all credential references in a dict."""
    resolved: dict[str, str] = {}
    for key, ref in creds.items():
        try:
            resolved[key] = resolve_credential(ref)
        except ValueError as exc:
            logger.warning("Failed to resolve credential %s: %s", key, exc)
    return resolved


def _resolve_vault(path: str) -> str:
    """Resolve a vault reference.

    Current implementation: file-based vault at ``~/.openhort/vault/``.
    Each secret is a file named by its path (slashes replaced with dots).
    Future: integrate with HashiCorp Vault, AWS Secrets Manager, etc.
    """
    vault_dir = Path.home() / ".openhort" / "vault"
    # path like "azure/client-id" → file "azure.client-id"
    filename = path.replace("/", ".")
    secret_file = vault_dir / filename
    if not secret_file.exists():
        raise ValueError(f"Vault secret not found: {path} (looked at {secret_file})")
    return secret_file.read_text().strip().split("\n")[0]


def _resolve_file(path: str) -> str:
    """Read a secret from a file (first line, stripped)."""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"Secret file not found: {path}")
    return p.read_text().strip().split("\n")[0]
