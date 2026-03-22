"""Token-based authentication — generated and verified on the host side.

The access server never stores or validates tokens. It:
1. Applies brute-force protection (artificial delay, rate limiting)
2. Forwards the token to the host via the tunnel
3. The host verifies the token and tells the proxy yes/no

Token types:
- **Temporary** — expires after a configured time (5min, 1h, 24h)
- **Permanent** — like an Azure key, valid until regenerated

Tokens are stored in a local JSON file on the host machine.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TokenRecord:
    """A stored access token."""

    token_hash: str  # SHA-256 hash of the token (never store plaintext)
    label: str
    permanent: bool
    created_at: float
    expires_at: float | None  # None = permanent
    last_used: float | None = None


class TokenStore:
    """Manages access tokens on the host side.

    Stored in a local JSON file. Tokens are hashed (SHA-256) — the
    plaintext is only shown once at creation time.
    """

    def __init__(self, path: str | Path = "~/.hort/tokens.json") -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tokens: list[TokenRecord] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self._tokens = [TokenRecord(**t) for t in data.get("tokens", [])]
            except (json.JSONDecodeError, TypeError):
                self._tokens = []

    def _save(self) -> None:
        data = {
            "tokens": [
                {
                    "token_hash": t.token_hash,
                    "label": t.label,
                    "permanent": t.permanent,
                    "created_at": t.created_at,
                    "expires_at": t.expires_at,
                    "last_used": t.last_used,
                }
                for t in self._tokens
            ]
        }
        self._path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_temporary(self, label: str = "Temporary", duration_seconds: int = 300) -> str:
        """Create a temporary token. Returns the plaintext token (shown once)."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        record = TokenRecord(
            token_hash=self._hash(token),
            label=label,
            permanent=False,
            created_at=now,
            expires_at=now + duration_seconds,
        )
        self._tokens.append(record)
        self._save()
        return token

    def create_permanent(self, label: str = "Permanent Key") -> str:
        """Create a permanent token. Invalidates any existing permanent token with the same label."""
        # Remove existing permanent token with same label
        self._tokens = [
            t for t in self._tokens
            if not (t.permanent and t.label == label)
        ]
        token = secrets.token_urlsafe(32)
        record = TokenRecord(
            token_hash=self._hash(token),
            label=label,
            permanent=True,
            created_at=time.time(),
            expires_at=None,
        )
        self._tokens.append(record)
        self._save()
        return token

    def verify(self, token: str) -> bool:
        """Verify a token. Returns True if valid and not expired."""
        token_hash = self._hash(token)
        now = time.time()
        # Clean expired temporary tokens
        self._tokens = [
            t for t in self._tokens
            if t.permanent or (t.expires_at is not None and t.expires_at > now)
        ]
        for t in self._tokens:
            if hmac.compare_digest(t.token_hash, token_hash):
                t.last_used = now
                self._save()
                return True
        return False

    def revoke_all_temporary(self) -> int:
        """Revoke all temporary tokens. Returns count removed."""
        before = len(self._tokens)
        self._tokens = [t for t in self._tokens if t.permanent]
        self._save()
        return before - len(self._tokens)

    def regenerate_permanent(self, label: str = "Permanent Key") -> str:
        """Regenerate a permanent token (old one invalidated). Returns new plaintext."""
        return self.create_permanent(label)

    def list_tokens(self) -> list[dict[str, object]]:
        """List all tokens (without hashes)."""
        now = time.time()
        return [
            {
                "label": t.label,
                "permanent": t.permanent,
                "created_at": t.created_at,
                "expires_at": t.expires_at,
                "expired": (not t.permanent and t.expires_at is not None and t.expires_at < now),
                "last_used": t.last_used,
            }
            for t in self._tokens
        ]
