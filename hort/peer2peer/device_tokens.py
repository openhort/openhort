"""Device token store — MongoDB-backed storage for paired mobile devices.

Each paired device gets a 256-bit token (secrets.token_urlsafe(32)). The
plaintext is shown once during pairing (via Telegram deep link or QR code)
and stored only on the device. The server stores the SHA-256 hash in MongoDB.

Verification is timing-safe (hmac.compare_digest) to prevent side-channel
attacks. Tokens never expire — revocation is explicit via revoke().

Security properties:
- 256-bit entropy: 2^256 keyspace, computationally unguessable
- SHA-256 hashed: plaintext not recoverable from DB
- Timing-safe: comparison immune to timing attacks
- One-way: DB compromise does not reveal tokens
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import secrets
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

logger = logging.getLogger(__name__)


class DeviceTokenStore:
    """Manages device pairing tokens in MongoDB.

    Collection schema::

        {
            "token_hash": "sha256_hex_string",
            "label": "Michael's iPhone",
            "created_at": "2026-04-04T10:00:00+00:00",
            "last_seen": "2026-04-04T12:30:00+00:00" | null
        }
    """

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017",
        db_name: str = "openhort",
        collection_name: str = "device_tokens",
    ) -> None:
        self._client: MongoClient[dict[str, Any]] = MongoClient(uri)
        self._db = self._client[db_name]
        self._col: Collection[dict[str, Any]] = self._db[collection_name]
        self._col.create_index("token_hash", unique=True)

    def create(self, label: str = "Device") -> str:
        """Generate a new device token. Returns plaintext (shown once, never stored)."""
        token = secrets.token_urlsafe(32)  # 256-bit entropy
        token_hash = self.hash_token(token)
        self._col.insert_one({
            "token_hash": token_hash,
            "label": label,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "last_seen": None,
        })
        logger.info("device token created: label=%s hash=%s...", label, token_hash[:12])
        return token

    def verify_hash(self, token_hash: str) -> bool:
        """Verify a device token hash against the store. Timing-safe."""
        for doc in self._col.find({}, {"token_hash": 1}):
            if hmac.compare_digest(doc["token_hash"], token_hash):
                return True
        return False

    def mark_seen(self, token_hash: str) -> None:
        """Update last_seen timestamp for a device."""
        self._col.update_one(
            {"token_hash": token_hash},
            {"$set": {"last_seen": datetime.datetime.now(datetime.UTC).isoformat()}},
        )

    def revoke(self, token_hash: str) -> bool:
        """Revoke a device token by its hash. Returns True if found and deleted."""
        result = self._col.delete_one({"token_hash": token_hash})
        if result.deleted_count > 0:
            logger.info("device token revoked: hash=%s...", token_hash[:12])
            return True
        return False

    def revoke_all(self) -> int:
        """Revoke all device tokens. Returns count deleted."""
        result = self._col.delete_many({})
        count: int = result.deleted_count
        if count:
            logger.info("all device tokens revoked: count=%d", count)
        return count

    def list_devices(self) -> list[dict[str, Any]]:
        """List all paired devices (hash, label, timestamps)."""
        devices = []
        for doc in self._col.find({}, {"_id": 0}):
            devices.append({
                "token_hash": doc["token_hash"],
                "label": doc.get("label", ""),
                "created_at": doc.get("created_at", ""),
                "last_seen": doc.get("last_seen"),
            })
        return devices

    @staticmethod
    def hash_token(token: str) -> str:
        """SHA-256 hash of a plaintext token (hex-encoded)."""
        return hashlib.sha256(token.encode()).hexdigest()
