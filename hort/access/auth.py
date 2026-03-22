"""Authentication — password hashing, brute-force protection, connection keys."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass, field


# ===== Password hashing (PBKDF2-SHA256, no external deps) =====

HASH_ITERATIONS = 100_000  # Balanced for single-core cloud instances
SALT_LENGTH = 32


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256. Returns 'pbkdf2:iterations:salt:hash'."""
    salt = os.urandom(SALT_LENGTH)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, HASH_ITERATIONS)
    return f"pbkdf2:{HASH_ITERATIONS}:{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        _, iterations_str, salt_hex, hash_hex = stored_hash.split(":")
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> str | None:
    """Check minimum password requirements. Returns error message or None."""
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return "Password must contain at least one digit"
    return None


# ===== Connection keys =====


def generate_connection_key() -> str:
    """Generate a secure connection key for host registration."""
    return secrets.token_urlsafe(32)


# ===== Brute-force protection =====


@dataclass
class RateLimiter:
    """Per-IP rate limiter with artificial delay for both success and failure."""

    _attempts: dict[str, list[float]] = field(default_factory=dict)
    window: float = 300.0  # 5 minutes
    max_attempts: int = 10
    base_delay: float = 0.5  # seconds — applied to ALL auth attempts

    def check(self, ip: str) -> bool:
        """Check if IP is allowed to attempt auth. Returns False if blocked."""
        now = time.monotonic()
        attempts = self._attempts.get(ip, [])
        # Clean old attempts
        attempts = [t for t in attempts if now - t < self.window]
        self._attempts[ip] = attempts
        return len(attempts) < self.max_attempts

    def record(self, ip: str) -> None:
        """Record an auth attempt (success or failure)."""
        now = time.monotonic()
        if ip not in self._attempts:
            self._attempts[ip] = []
        self._attempts[ip].append(now)

    def get_delay(self, ip: str) -> float:
        """Get artificial delay for this IP (increases with attempts)."""
        attempts = len(self._attempts.get(ip, []))
        # Exponential backoff: 0.5s, 1s, 2s, 4s... capped at 10s
        delay: float = min(self.base_delay * (2 ** max(0, attempts - 3)), 10.0)
        return delay
