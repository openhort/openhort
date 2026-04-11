"""MongoDB-compatible document store backed by SQLite.

Supports a useful subset of the MongoDB query/update API:

Queries (filter):
    {"name": "x"}                    — exact match
    {"age": {"$gt": 18}}             — comparison ($gt, $gte, $lt, $lte, $ne)
    {"tags": {"$in": ["a", "b"]}}    — in list
    {"$and": [{...}, {...}]}         — logical AND
    {"$or": [{...}, {...}]}          — logical OR

Updates:
    {"$set": {"name": "y"}}          — set fields
    {"$unset": {"old_field": ""}}    — remove fields
    {"$inc": {"counter": 1}}         — increment number

TTL:
    Every document can have a TTL (seconds from insert/update).
    Expired documents are invisible to queries and garbage-collected.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ScrollStore:
    """Per-namespace scroll store with MongoDB-compatible API.

    Each collection is a table in a single SQLite database.
    Documents are JSON blobs with an ``_id`` primary key.
    TTL is enforced via an ``_expires_at`` column.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # Create the meta table
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _collections (
                name TEXT PRIMARY KEY,
                default_ttl INTEGER
            )
        """)
        conn.commit()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _ensure_collection(self, name: str) -> None:
        conn = self._conn()
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS [{name}] (
                _id TEXT PRIMARY KEY,
                doc TEXT NOT NULL,
                _created_at REAL NOT NULL,
                _updated_at REAL NOT NULL,
                _expires_at REAL
            )
        """)
        safe = name.replace("-", "_").replace("/", "_").replace(" ", "_")
        conn.execute(f"CREATE INDEX IF NOT EXISTS [idx_{safe}_expires] ON [{name}](_expires_at)")
        conn.commit()

    # ── Insert ──

    def insert(
        self, collection: str, doc: dict[str, Any],
        ttl: int | None = None, access: str = "private",
    ) -> str:
        """Insert a document. Returns the ``_id``.

        Args:
            access: "private" (owner only), "shared" (permitted llmings), "public" (anyone)
        """
        self._ensure_collection(collection)
        doc_id = doc.get("_id", str(uuid.uuid4()))
        doc["_id"] = doc_id
        doc["_access"] = access
        now = time.time()
        expires = now + ttl if ttl else None

        self._conn().execute(
            f"INSERT OR REPLACE INTO [{collection}] (_id, doc, _created_at, _updated_at, _expires_at) VALUES (?, ?, ?, ?, ?)",
            (doc_id, json.dumps(doc), now, now, expires),
        )
        self._conn().commit()
        return doc_id

    # ── Find ──

    def find_one(self, collection: str, filt: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Find a single document matching the filter."""
        results = self.find(collection, filt, limit=1)
        return results[0] if results else None

    def find(
        self, collection: str, filt: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int = 0, skip: int = 0,
    ) -> list[dict[str, Any]]:
        """Find documents matching the filter."""
        self._ensure_collection(collection)
        now = time.time()
        rows = self._conn().execute(
            f"SELECT doc FROM [{collection}] WHERE (_expires_at IS NULL OR _expires_at > ?)",
            (now,),
        ).fetchall()

        docs = [json.loads(r["doc"]) for r in rows]

        if filt:
            docs = [d for d in docs if _match(d, filt)]

        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda d: d.get(key, ""), reverse=(direction == -1))

        if skip:
            docs = docs[skip:]
        if limit:
            docs = docs[:limit]

        return docs

    def count(self, collection: str, filt: dict[str, Any] | None = None) -> int:
        """Count documents matching the filter."""
        return len(self.find(collection, filt))

    # ── Update ──

    def update_one(
        self, collection: str, filt: dict[str, Any], update: dict[str, Any],
        ttl: int | None = None,
    ) -> dict[str, Any]:
        """Update a single document. Returns ``{matched, modified}``."""
        doc = self.find_one(collection, filt)
        if doc is None:
            return {"matched": 0, "modified": 0}

        _apply_update(doc, update)
        now = time.time()
        expires = now + ttl if ttl else None

        self._conn().execute(
            f"UPDATE [{collection}] SET doc=?, _updated_at=?, _expires_at=COALESCE(?, _expires_at) WHERE _id=?",
            (json.dumps(doc), now, expires, doc["_id"]),
        )
        self._conn().commit()
        return {"matched": 1, "modified": 1}

    def update_many(
        self, collection: str, filt: dict[str, Any], update: dict[str, Any],
    ) -> dict[str, Any]:
        """Update all matching documents."""
        docs = self.find(collection, filt)
        now = time.time()
        for doc in docs:
            _apply_update(doc, update)
            self._conn().execute(
                f"UPDATE [{collection}] SET doc=?, _updated_at=? WHERE _id=?",
                (json.dumps(doc), now, doc["_id"]),
            )
        self._conn().commit()
        return {"matched": len(docs), "modified": len(docs)}

    # ── Delete ──

    def delete_one(self, collection: str, filt: dict[str, Any]) -> dict[str, Any]:
        """Delete a single document."""
        doc = self.find_one(collection, filt)
        if doc is None:
            return {"deleted": 0}
        self._conn().execute(f"DELETE FROM [{collection}] WHERE _id=?", (doc["_id"],))
        self._conn().commit()
        return {"deleted": 1}

    def delete_many(self, collection: str, filt: dict[str, Any] | None = None) -> dict[str, Any]:
        """Delete all matching documents. Empty filter deletes all."""
        if not filt:
            cursor = self._conn().execute(f"DELETE FROM [{collection}]")
            self._conn().commit()
            return {"deleted": cursor.rowcount}
        docs = self.find(collection, filt)
        ids = [d["_id"] for d in docs]
        if ids:
            placeholders = ",".join(["?"] * len(ids))
            self._conn().execute(f"DELETE FROM [{collection}] WHERE _id IN ({placeholders})", ids)
            self._conn().commit()
        return {"deleted": len(ids)}

    # ── TTL garbage collection ──

    def gc(self) -> int:
        """Remove expired documents from all collections. Returns count removed."""
        now = time.time()
        total = 0
        for name in self.collections():
            try:
                cursor = self._conn().execute(
                    f"DELETE FROM [{name}] WHERE _expires_at IS NOT NULL AND _expires_at <= ?",
                    (now,),
                )
                total += cursor.rowcount
            except Exception:
                pass
        if total:
            self._conn().commit()
            logger.debug("GC: removed %d expired documents", total)
        return total

    def collections(self) -> list[str]:
        """List all collections."""
        rows = self._conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
        ).fetchall()
        return [r["name"] for r in rows]

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ── MongoDB filter matching ──

def _match(doc: dict[str, Any], filt: dict[str, Any]) -> bool:
    """Match a document against a MongoDB-style filter."""
    for key, value in filt.items():
        if key == "$and":
            return all(_match(doc, f) for f in value)
        if key == "$or":
            return any(_match(doc, f) for f in value)

        doc_val = doc.get(key)

        if isinstance(value, dict):
            for op, cmp_val in value.items():
                if op == "$gt" and not (doc_val is not None and doc_val > cmp_val):
                    return False
                elif op == "$gte" and not (doc_val is not None and doc_val >= cmp_val):
                    return False
                elif op == "$lt" and not (doc_val is not None and doc_val < cmp_val):
                    return False
                elif op == "$lte" and not (doc_val is not None and doc_val <= cmp_val):
                    return False
                elif op == "$ne" and doc_val == cmp_val:
                    return False
                elif op == "$in" and doc_val not in cmp_val:
                    return False
                elif op == "$exists" and (key in doc) != cmp_val:
                    return False
        else:
            if doc_val != value:
                return False
    return True


def _apply_update(doc: dict[str, Any], update: dict[str, Any]) -> None:
    """Apply MongoDB-style update operators to a document."""
    if "$set" in update:
        for k, v in update["$set"].items():
            doc[k] = v
    if "$unset" in update:
        for k in update["$unset"]:
            doc.pop(k, None)
    if "$inc" in update:
        for k, v in update["$inc"].items():
            doc[k] = doc.get(k, 0) + v
    if "$push" in update:
        for k, v in update["$push"].items():
            if k not in doc:
                doc[k] = []
            doc[k].append(v)
    # If no operators, treat as a full replacement (except _id)
    if not any(k.startswith("$") for k in update):
        _id = doc.get("_id")
        doc.clear()
        doc.update(update)
        if _id:
            doc["_id"] = _id
