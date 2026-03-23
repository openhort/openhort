"""Plugin file store — per-plugin binary file storage with deprecation/TTL.

Each plugin gets its own isolated file store via ``PluginContext.files``.
Files are stored locally on disk. Metadata (mime type, expiry) tracked in a
sidecar JSON file. For remote/cloud storage, a separate blob storage plugin
can implement the same interface — MongoDB is NOT used for file storage.

Backends:

- ``LocalFileStore`` — local filesystem (default)
- Future: ``BlobFileStore`` — Azure Blob / S3 (via plugin)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileInfo:
    """Metadata about a stored file."""

    name: str
    mime_type: str
    size: int
    created_at: float
    expires_at: float | None


class PluginFileStore(ABC):
    """Per-plugin file storage with optional expiration."""

    @abstractmethod
    async def save(
        self,
        name: str,
        data: bytes,
        mime_type: str = "",
        ttl_seconds: float | None = None,
    ) -> str:
        """Save a file. Returns the storage URI. Overwrites if exists."""

    @abstractmethod
    async def load(self, name: str) -> tuple[bytes, str] | None:
        """Load a file. Returns (data, mime_type) or None if missing/expired."""

    @abstractmethod
    async def delete(self, name: str) -> bool:
        """Delete a file. Returns True if it existed."""

    @abstractmethod
    async def list_files(self, prefix: str = "") -> list[FileInfo]:
        """List non-expired files, optionally filtered by name prefix."""

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove all expired files. Returns count removed."""


class LocalFileStore(PluginFileStore):
    """Local filesystem file store.

    Files at ``{base_dir}/{plugin_id}/files/{name}``.
    Metadata in ``{base_dir}/{plugin_id}/files/_meta.json``.
    """

    def __init__(self, plugin_id: str, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path("~/.hort/plugins").expanduser()
        self._dir = base_dir / plugin_id / "files"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._meta_path = self._dir / "_meta.json"
        self._lock = threading.Lock()

    def _load_meta_sync(self) -> dict[str, Any]:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_meta_sync(self, meta: dict[str, Any]) -> None:
        self._meta_path.write_text(json.dumps(meta, indent=2))

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        expires = entry.get("expires_at")
        return expires is not None and time.time() > expires

    async def _run(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    async def save(
        self,
        name: str,
        data: bytes,
        mime_type: str = "",
        ttl_seconds: float | None = None,
    ) -> str:
        with self._lock:
            file_path = self._dir / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            await self._run(file_path.write_bytes, data)
            meta = await self._run(self._load_meta_sync)
            now = time.time()
            meta[name] = {
                "mime_type": mime_type,
                "size": len(data),
                "created_at": now,
                "expires_at": now + ttl_seconds if ttl_seconds else None,
            }
            await self._run(self._save_meta_sync, meta)
            return f"file://{name}"

    async def load(self, name: str) -> tuple[bytes, str] | None:
        with self._lock:
            meta = await self._run(self._load_meta_sync)
            entry = meta.get(name)
            if entry is None:
                return None
            if self._is_expired(entry):
                # Clean up expired file
                file_path = self._dir / name
                if file_path.exists():
                    await self._run(file_path.unlink)
                del meta[name]
                await self._run(self._save_meta_sync, meta)
                return None
            file_path = self._dir / name
            if not file_path.exists():
                return None
            data = await self._run(file_path.read_bytes)
            return data, entry.get("mime_type", "")

    async def delete(self, name: str) -> bool:
        with self._lock:
            meta = await self._run(self._load_meta_sync)
            if name not in meta:
                return False
            del meta[name]
            await self._run(self._save_meta_sync, meta)
            file_path = self._dir / name
            if file_path.exists():
                await self._run(file_path.unlink)
            return True

    async def list_files(self, prefix: str = "") -> list[FileInfo]:
        with self._lock:
            meta = await self._run(self._load_meta_sync)
            results: list[FileInfo] = []
            for name, entry in meta.items():
                if not name.startswith(prefix):
                    continue
                if self._is_expired(entry):
                    continue
                results.append(
                    FileInfo(
                        name=name,
                        mime_type=entry.get("mime_type", ""),
                        size=entry.get("size", 0),
                        created_at=entry.get("created_at", 0),
                        expires_at=entry.get("expires_at"),
                    )
                )
            return results

    async def cleanup_expired(self) -> int:
        with self._lock:
            meta = await self._run(self._load_meta_sync)
            expired = [k for k, v in meta.items() if self._is_expired(v)]
            for name in expired:
                del meta[name]
                file_path = self._dir / name
                if file_path.exists():
                    await self._run(file_path.unlink)
            if expired:
                await self._run(self._save_meta_sync, meta)
            return len(expired)
