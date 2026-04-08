"""Credential type definitions and data models.

Every llming declares its credential needs in ``extension.json``.
The credential system uses these specs to render setup UIs,
validate inputs, and manage the lifecycle.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class CredentialType(str, enum.Enum):
    """Supported credential types — each has its own UI and validation."""

    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    USERNAME_PASSWORD = "username_password"
    CONNECTION_STRING = "connection_string"
    BEARER_TOKEN = "bearer_token"
    KEYCHAIN = "keychain"


class CredentialStatus(str, enum.Enum):
    """Lifecycle status of a stored credential."""

    UNCONFIGURED = "unconfigured"  # never set
    VALID = "valid"                # working
    EXPIRING = "expiring"          # will expire soon (< 1h)
    EXPIRED = "expired"            # token expired, needs refresh or re-auth
    ERROR = "error"                # validation failed
    REVOKED = "revoked"            # explicitly revoked by user


@dataclass
class CredentialSpec:
    """Declaration of a credential a llming needs.

    Parsed from ``extension.json`` or ``hort-config.yaml``.
    Drives the setup UI and validation logic.
    """

    id: str                                     # unique within the llming
    type: CredentialType
    label: str = ""                             # human-readable name
    required: bool = True

    # OAuth2
    provider: str = ""                          # "microsoft", "google", etc.
    scopes: list[str] = field(default_factory=list)
    client_id: str = ""                         # can be env: or vault: ref
    auth_url: str = ""                          # authorization endpoint
    token_url: str = ""                         # token exchange endpoint

    # API key / bearer token
    placeholder: str = ""                       # input placeholder (e.g. "sk-...")
    validate_url: str = ""                      # GET/POST to verify the key
    validate_method: str = "GET"                # HTTP method for validation
    validate_header: str = "Authorization"      # header name for the key
    validate_header_prefix: str = "Bearer "     # prefix before the key value

    # Username/password
    # Uses validate_url with POST {username, password}

    # Connection string
    default_port: int = 0                       # default port for the service

    # Keychain
    service: str = ""                           # OS keychain service name

    # UI
    help_url: str = ""                          # link to docs for getting the key
    help_text: str = ""                         # inline help text

    # Lifecycle
    expires: bool = False                       # does this credential expire?
    refresh_supported: bool = False             # can it auto-refresh?
    remote_update: bool = False                 # allow update via proxy/P2P?
    health_check_interval: int = 300            # seconds between health checks (0=disabled)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialSpec:
        """Parse from manifest or YAML config."""
        ctype = data.get("type", "api_key")
        if isinstance(ctype, str):
            ctype = CredentialType(ctype)
        return cls(
            id=data.get("id", "default"),
            type=ctype,
            label=data.get("label", data.get("id", "")),
            required=data.get("required", True),
            provider=data.get("provider", ""),
            scopes=data.get("scopes", []),
            client_id=data.get("client_id", ""),
            auth_url=data.get("auth_url", ""),
            token_url=data.get("token_url", ""),
            placeholder=data.get("placeholder", ""),
            validate_url=data.get("validate_url", ""),
            validate_method=data.get("validate_method", "GET"),
            validate_header=data.get("validate_header", "Authorization"),
            validate_header_prefix=data.get("validate_header_prefix", "Bearer "),
            default_port=data.get("default_port", 0),
            service=data.get("service", ""),
            help_url=data.get("help_url", ""),
            help_text=data.get("help_text", ""),
            expires=data.get("expires", False),
            refresh_supported=data.get("refresh_supported", False),
            remote_update=data.get("remote_update", False),
            health_check_interval=data.get("health_check_interval", 300),
        )


@dataclass
class CredentialInfo:
    """Stored credential metadata (no secret values)."""

    llming_name: str
    credential_id: str
    credential_type: CredentialType
    status: CredentialStatus
    label: str = ""
    created_at: str = ""
    updated_at: str = ""
    expires_at: str | None = None
    provider: str = ""
    scopes: list[str] = field(default_factory=list)
    remote_update: bool = False


@dataclass
class CredentialAlert:
    """Notification for a credential that needs attention."""

    llming_name: str
    credential_id: str
    label: str
    status: CredentialStatus
    message: str
    action: str = "re-authenticate"  # "re-authenticate", "retry", "edit"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ===== Well-known OAuth2 providers =====

OAUTH2_PROVIDERS: dict[str, dict[str, str]] = {
    "microsoft": {
        "auth_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "device_code_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
        "default_tenant": "common",
    },
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "device_code_url": "https://oauth2.googleapis.com/device/code",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "device_code_url": "https://github.com/login/device/code",
    },
}
