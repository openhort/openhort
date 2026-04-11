"""Azure Blob Storage-compatible file store backed by local filesystem.

API mirrors Azure Blob Storage concepts:
- Containers (directories) for grouping crates
- Crates (files) with metadata, content type, TTL
- List, get, put, delete, exists, head

TTL is tracked in a SQLite metadata database. Expired crates
are invisible to queries and garbage-collected.

All crate access goes through this API — no direct filesystem access.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CrateInfo:
    """Metadata about a crate (returned by head/list)."""
    name: str
    container: str
    size: int
    content_type: str
    created_at: float
    updated_at: float
    expires_at: float | None
    metadata: dict[str, str]
    etag: str
    access: str = "private"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "container": self.container,
            "size": self.size,
            "content_type": self.content_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
            "etag": self.etag,
        }


class CrateStore:
    """Per-namespace crate store with Azure Blob-compatible API.

    Crates are stored as files on disk. Metadata (size, content type,
    TTL, custom metadata) is tracked in SQLite.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        self._db_path = self._base / "_blobs.db"
        self._local = threading.local()
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blobs (
                container TEXT NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL,
                metadata TEXT DEFAULT '{}',
                etag TEXT NOT NULL,
                access TEXT NOT NULL DEFAULT 'private',
                PRIMARY KEY (container, name)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_blobs_expires ON blobs(expires_at)")
        conn.commit()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    # ── Put ──

    def put(
        self, container: str, name: str, data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        ttl: int | None = None,
        access: str = "private",
    ) -> CrateInfo:
        """Upload a crate. Overwrites if exists.

        Args:
            access: "private" (owner only), "shared" (permitted llmings), "public" (anyone)
        """
        container_dir = self._base / container
        container_dir.mkdir(parents=True, exist_ok=True)

        # Safe filename
        safe_name = name.replace("/", "_").replace("\\", "_")
        file_path = container_dir / safe_name
        file_path.write_bytes(data)

        now = time.time()
        expires = now + ttl if ttl else None
        etag = uuid.uuid4().hex[:16]
        meta_json = json.dumps(metadata or {})

        self._conn().execute(
            """INSERT OR REPLACE INTO blobs
               (container, name, file_path, size, content_type, created_at, updated_at, expires_at, metadata, etag, access)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (container, name, str(file_path), len(data), content_type, now, now, expires, meta_json, etag, access),
        )
        self._conn().commit()

        return CrateInfo(
            name=name, container=container, size=len(data),
            content_type=content_type, created_at=now, updated_at=now,
            expires_at=expires, metadata=metadata or {}, etag=etag,
            access=access,
        )

    # ── Get ──

    def get(self, container: str, name: str) -> tuple[bytes, CrateInfo] | None:
        """Download a crate. Returns (data, info) or None."""
        info = self.head(container, name)
        if info is None:
            return None
        row = self._conn().execute(
            "SELECT file_path FROM blobs WHERE container=? AND name=?",
            (container, name),
        ).fetchone()
        if not row:
            return None
        try:
            data = Path(row["file_path"]).read_bytes()
            return data, info
        except FileNotFoundError:
            # File deleted but metadata remains — clean up
            self._conn().execute("DELETE FROM blobs WHERE container=? AND name=?", (container, name))
            self._conn().commit()
            return None

    # ── Head ──

    def head(self, container: str, name: str) -> CrateInfo | None:
        """Get crate metadata without downloading."""
        now = time.time()
        row = self._conn().execute(
            "SELECT * FROM blobs WHERE container=? AND name=? AND (expires_at IS NULL OR expires_at > ?)",
            (container, name, now),
        ).fetchone()
        if not row:
            return None
        return CrateInfo(
            name=row["name"], container=row["container"],
            size=row["size"], content_type=row["content_type"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            metadata=json.loads(row["metadata"] or "{}"),
            etag=row["etag"],
        )

    # ── List ──

    def list(self, container: str, prefix: str = "") -> list[CrateInfo]:
        """List crates in a container, optionally filtered by prefix."""
        now = time.time()
        rows = self._conn().execute(
            "SELECT * FROM blobs WHERE container=? AND (expires_at IS NULL OR expires_at > ?)",
            (container, now),
        ).fetchall()
        result = []
        for row in rows:
            if prefix and not row["name"].startswith(prefix):
                continue
            result.append(CrateInfo(
                name=row["name"], container=row["container"],
                size=row["size"], content_type=row["content_type"],
                created_at=row["created_at"], updated_at=row["updated_at"],
                expires_at=row["expires_at"],
                metadata=json.loads(row["metadata"] or "{}"),
                etag=row["etag"],
            ))
        return result

    # ── Delete ──

    def delete(self, container: str, name: str) -> bool:
        """Delete a crate. Returns True if existed."""
        row = self._conn().execute(
            "SELECT file_path FROM blobs WHERE container=? AND name=?",
            (container, name),
        ).fetchone()
        if not row:
            return False
        try:
            Path(row["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        self._conn().execute("DELETE FROM blobs WHERE container=? AND name=?", (container, name))
        self._conn().commit()
        return True

    def exists(self, container: str, name: str) -> bool:
        """Check if a crate exists (and is not expired)."""
        return self.head(container, name) is not None

    # ── Container operations ──

    def delete_container(self, container: str) -> int:
        """Delete all crates in a container. Returns count deleted."""
        rows = self._conn().execute(
            "SELECT file_path FROM blobs WHERE container=?", (container,)
        ).fetchall()
        for row in rows:
            try:
                Path(row["file_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        cursor = self._conn().execute("DELETE FROM blobs WHERE container=?", (container,))
        self._conn().commit()
        # Remove directory
        container_dir = self._base / container
        if container_dir.exists():
            shutil.rmtree(container_dir, ignore_errors=True)
        return cursor.rowcount

    def list_containers(self) -> list[str]:
        """List all containers."""
        rows = self._conn().execute("SELECT DISTINCT container FROM blobs").fetchall()
        return [r["container"] for r in rows]

    # ── TTL garbage collection ──

    def gc(self) -> int:
        """Remove expired crates. Returns count removed."""
        now = time.time()
        rows = self._conn().execute(
            "SELECT container, name, file_path FROM blobs WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        ).fetchall()
        for row in rows:
            try:
                Path(row["file_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        if rows:
            self._conn().execute(
                "DELETE FROM blobs WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
            self._conn().commit()
            logger.debug("GC: removed %d expired crates", len(rows))
        return len(rows)

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
