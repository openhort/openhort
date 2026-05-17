"""Device token store for paired mobile devices.

Each paired device gets a 256-bit token.  The plaintext is shown once during
pairing and stored only on the device.  The server stores only SHA-256 hashes.

Default storage is a local JSON file in the temp directory.  Passing a
``mongodb://`` or ``mongodb+srv://`` URI keeps the historical MongoDB backend.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DeviceTokenStore:
    """Manages durable paired-device tokens."""

    def __init__(
        self,
        uri: str = "",
        db_name: str = "openhort",
        collection_name: str = "device_tokens",
        path: str | Path | None = None,
    ) -> None:
        self._mode = "json"
        self._lock = threading.Lock()
        self._path = Path(path) if path else Path(tempfile.gettempdir()) / "openhort-device-tokens.json"
        self._client: Any = None
        self._col: Any = None
        if uri.startswith(("mongodb://", "mongodb+srv://")):
            from pymongo import MongoClient

            self._mode = "mongo"
            self._client = MongoClient(uri)
            self._db = self._client[db_name]
            self._col = self._db[collection_name]
            self._col.create_index("token_hash", unique=True)

    def create(self, label: str = "Device", app_name: str = "", icon: str = "") -> str:
        """Generate a new device token. Returns plaintext, never stored."""
        token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(token)
        doc = {
            "token_hash": token_hash,
            "label": label,
            "app_name": app_name,
            "icon": icon,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "last_seen": None,
        }
        if self._mode == "mongo":
            self._col.insert_one(doc)
        else:
            docs = [d for d in self._load_json() if d.get("token_hash") != token_hash]
            docs.append(doc)
            self._save_json(docs)
        logger.info("device token created: label=%s hash=%s...", label, token_hash[:12])
        return token

    def verify_hash(self, token_hash: str) -> bool:
        """Verify a device token hash against the store. Timing-safe."""
        docs = self._col.find({}, {"token_hash": 1}) if self._mode == "mongo" else self._load_json()
        for doc in docs:
            if hmac.compare_digest(doc.get("token_hash", ""), token_hash):
                return True
        return False

    def mark_seen(self, token_hash: str) -> None:
        """Update last_seen timestamp for a device."""
        now = datetime.datetime.now(datetime.UTC).isoformat()
        if self._mode == "mongo":
            self._col.update_one({"token_hash": token_hash}, {"$set": {"last_seen": now}})
            return
        docs = self._load_json()
        for doc in docs:
            if hmac.compare_digest(doc.get("token_hash", ""), token_hash):
                doc["last_seen"] = now
        self._save_json(docs)

    def revoke(self, token_hash: str) -> bool:
        """Revoke a device token by its hash. Returns True if found."""
        if self._mode == "mongo":
            result = self._col.delete_one({"token_hash": token_hash})
            ok = result.deleted_count > 0
        else:
            docs = self._load_json()
            kept = [d for d in docs if not hmac.compare_digest(d.get("token_hash", ""), token_hash)]
            ok = len(kept) != len(docs)
            self._save_json(kept)
        if ok:
            logger.info("device token revoked: hash=%s...", token_hash[:12])
        return ok

    def revoke_all(self) -> int:
        """Revoke all device tokens. Returns count deleted."""
        if self._mode == "mongo":
            result = self._col.delete_many({})
            count: int = result.deleted_count
        else:
            docs = self._load_json()
            count = len(docs)
            self._save_json([])
        if count:
            logger.info("all device tokens revoked: count=%d", count)
        return count

    def list_devices(self) -> list[dict[str, Any]]:
        """List all paired devices."""
        docs = self._col.find({}, {"_id": 0}) if self._mode == "mongo" else self._load_json()
        return [
            {
                "token_hash": doc["token_hash"],
                "label": doc.get("label", ""),
                "app_name": doc.get("app_name", ""),
                "icon": doc.get("icon", ""),
                "created_at": doc.get("created_at", ""),
                "last_seen": doc.get("last_seen"),
            }
            for doc in docs
        ]

    def _load_json(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                data = json.loads(self._path.read_text())
            except (OSError, json.JSONDecodeError):
                return []
        return data if isinstance(data, list) else []

    def _save_json(self, docs: list[dict[str, Any]]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(docs, indent=2, sort_keys=True))
            tmp.replace(self._path)

    @staticmethod
    def hash_token(token: str) -> str:
        """SHA-256 hash of a plaintext token."""
        return hashlib.sha256(token.encode()).hexdigest()
