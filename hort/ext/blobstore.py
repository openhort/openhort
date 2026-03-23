"""Local blob storage — simple, deadlock-free key-value store on disk.

One central class that handles everything: store, list, fetch, delete.
Used by ``FilePluginStore`` and ``LocalFileStore`` as their backend.

Design:
- Each blob is a single file: ``{base_dir}/{namespace}/{key}``
- No locks — writes use atomic temp-file-then-rename (POSIX atomic)
- Metadata (TTL, mime type) stored as a JSON sidecar: ``{key}._meta``
- Namespace isolation: each plugin gets its own subdirectory
- Survives hot-reloads, crashes, and process restarts — no shared state

All methods are synchronous (called from executor threads via ``_run``).
The async wrappers in ``FilePluginStore`` and ``LocalFileStore`` call
these via ``loop.run_in_executor()``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BlobMeta:
    """Metadata for a stored blob."""
    key: str
    size: int
    mime_type: str = ""
    created_at: float = 0.0
    expires_at: float | None = None

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at


class LocalBlobStore:
    """Deadlock-free local blob storage.

    Each blob is a file on disk. Writes use atomic rename.
    No locks, no shared state, no deadlocks.

    Usage::

        store = LocalBlobStore("~/.hort/plugins", "my-plugin")
        store.put("config", b'{"key": "value"}', mime_type="application/json")
        data = store.get("config")   # → bytes or None
        store.put("temp", b'data', ttl_seconds=3600)  # auto-expires
        store.delete("config")
        keys = store.list_keys()
        store.cleanup_expired()
    """

    def __init__(self, base_dir: str | Path, namespace: str) -> None:
        self._dir = Path(base_dir).expanduser() / namespace
        self._dir.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, key: str) -> Path:
        # Sanitize key — replace / with _ to keep flat directory
        safe = key.replace("/", "_").replace("..", "_")
        return self._dir / safe

    def _meta_path(self, key: str) -> Path:
        return Path(str(self._blob_path(key)) + "._meta")

    def _read_meta(self, key: str) -> BlobMeta | None:
        mp = self._meta_path(key)
        if not mp.exists():
            bp = self._blob_path(key)
            if bp.exists():
                return BlobMeta(key=key, size=bp.stat().st_size, created_at=bp.stat().st_mtime)
            return None
        try:
            d = json.loads(mp.read_text())
            return BlobMeta(
                key=key,
                size=d.get("size", 0),
                mime_type=d.get("mime_type", ""),
                created_at=d.get("created_at", 0),
                expires_at=d.get("expires_at"),
            )
        except (json.JSONDecodeError, OSError):
            return None

    def _write_meta(self, key: str, meta: BlobMeta) -> None:
        mp = self._meta_path(key)
        _atomic_write(mp, json.dumps({
            "size": meta.size,
            "mime_type": meta.mime_type,
            "created_at": meta.created_at,
            "expires_at": meta.expires_at,
        }).encode())

    # ===== Public API =====

    def put(
        self, key: str, data: bytes,
        mime_type: str = "", ttl_seconds: float | None = None,
    ) -> None:
        """Store a blob. Atomic write via temp file + rename."""
        bp = self._blob_path(key)
        _atomic_write(bp, data)
        now = time.time()
        meta = BlobMeta(
            key=key, size=len(data), mime_type=mime_type,
            created_at=now,
            expires_at=now + ttl_seconds if ttl_seconds else None,
        )
        self._write_meta(key, meta)

    def get(self, key: str) -> bytes | None:
        """Fetch a blob. Returns None if missing or expired."""
        meta = self._read_meta(key)
        if meta is None:
            return None
        if meta.expired:
            self.delete(key)
            return None
        bp = self._blob_path(key)
        try:
            return bp.read_bytes()
        except OSError:
            return None

    def get_meta(self, key: str) -> BlobMeta | None:
        """Get metadata without reading the blob data."""
        meta = self._read_meta(key)
        if meta and meta.expired:  # pragma: no cover
            self.delete(key)
            return None
        return meta

    def delete(self, key: str) -> bool:
        """Delete a blob + metadata. Returns True if it existed."""
        bp = self._blob_path(key)
        mp = self._meta_path(key)
        existed = bp.exists()
        bp.unlink(missing_ok=True)
        mp.unlink(missing_ok=True)
        return existed

    def list_keys(self, prefix: str = "") -> list[str]:
        """List non-expired blob keys, optionally filtered by prefix."""
        keys = []
        for f in self._dir.iterdir():
            if f.name.endswith("._meta") or f.name.startswith("."):
                continue
            key = f.name
            if prefix and not key.startswith(prefix):
                continue
            meta = self._read_meta(key)
            if meta and not meta.expired:
                keys.append(key)
        return sorted(keys)

    def list_metas(self, prefix: str = "") -> list[BlobMeta]:
        """List metadata for non-expired blobs."""
        result = []
        for key in self.list_keys(prefix):
            meta = self._read_meta(key)
            if meta:
                result.append(meta)
        return result

    def cleanup_expired(self) -> int:
        """Remove all expired blobs. Returns count removed."""
        count = 0
        for f in list(self._dir.iterdir()):
            if f.name.endswith("._meta") or f.name.startswith("."):
                continue
            meta = self._read_meta(f.name)
            if meta and meta.expired:
                self.delete(f.name)
                count += 1
        return count

    def put_json(self, key: str, value: dict[str, Any], ttl_seconds: float | None = None) -> None:
        """Convenience: store a dict as JSON blob."""
        self.put(key, json.dumps(value).encode(), mime_type="application/json", ttl_seconds=ttl_seconds)

    def get_json(self, key: str) -> dict[str, Any] | None:
        """Convenience: fetch a JSON blob as dict."""
        data = self.get(key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None


def _atomic_write(path: Path, data: bytes) -> None:
    """Write data to file atomically using temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        os.write(fd, data)
        os.close(fd)
        os.replace(tmp, str(path))  # atomic on POSIX
    except Exception:  # pragma: no cover
        try:
            os.close(fd)
        except OSError:
            pass
        Path(tmp).unlink(missing_ok=True)
        raise
