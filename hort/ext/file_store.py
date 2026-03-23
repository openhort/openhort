"""Plugin file store — per-plugin binary file storage with deprecation/TTL.

Backed by ``LocalBlobStore`` — no locks, no deadlocks, atomic writes.
For remote/cloud storage, a blob storage plugin can implement the same interface.
"""

from __future__ import annotations

import asyncio
import logging
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
        self, name: str, data: bytes, mime_type: str = "",
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
    """Local file storage backed by ``LocalBlobStore``.

    No locks — uses atomic file writes via the blob store.
    """

    def __init__(self, plugin_id: str, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path("~/.hort/plugins").expanduser()
        from hort.ext.blobstore import LocalBlobStore
        self._blobs = LocalBlobStore(base_dir, plugin_id + ".files")

    async def _run(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    async def save(
        self, name: str, data: bytes, mime_type: str = "",
        ttl_seconds: float | None = None,
    ) -> str:
        await self._run(self._blobs.put, name, data, mime_type, ttl_seconds)
        return f"file://{name}"

    async def load(self, name: str) -> tuple[bytes, str] | None:
        def _load() -> tuple[bytes, str] | None:
            data = self._blobs.get(name)
            if data is None:
                return None
            meta = self._blobs.get_meta(name)
            return data, meta.mime_type if meta else ""
        return await self._run(_load)

    async def delete(self, name: str) -> bool:
        return await self._run(self._blobs.delete, name)

    async def list_files(self, prefix: str = "") -> list[FileInfo]:
        def _list() -> list[FileInfo]:
            return [
                FileInfo(
                    name=m.key, mime_type=m.mime_type, size=m.size,
                    created_at=m.created_at, expires_at=m.expires_at,
                )
                for m in self._blobs.list_metas(prefix)
            ]
        return await self._run(_list)

    async def cleanup_expired(self) -> int:
        return await self._run(self._blobs.cleanup_expired)
