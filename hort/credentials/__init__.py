"""Unified credential management for llmings.

Key classes:
- ``CredentialVault`` — encrypted storage (SQLite + Fernet)
- ``CredentialManager`` — access control proxy
- ``CredentialAccess`` — scoped access for a single llming (injected into PluginContext)
- ``CredentialSpec`` — what a llming needs (from manifest)
"""

from hort.credentials.manager import (
    CredentialAccess,
    CredentialManager,
    get_credential_manager,
)
from hort.credentials.types import (
    CredentialAlert,
    CredentialInfo,
    CredentialSpec,
    CredentialStatus,
    CredentialType,
)
from hort.credentials.vault import CredentialVault, get_vault

__all__ = [
    "CredentialAccess",
    "CredentialAlert",
    "CredentialInfo",
    "CredentialManager",
    "CredentialSpec",
    "CredentialStatus",
    "CredentialType",
    "CredentialVault",
    "get_credential_manager",
    "get_vault",
]
