"""Per-llming namespaced key-value storage with TTL.

Each llming gets its own isolated store via ``LlmingBase.store``.
Backed by ``LocalBlobStore`` — no locks, no deadlocks, atomic writes.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PluginStore(ABC):
    """Per-plugin namespaced key-value store with optional TTL."""

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """Get a document by key. Returns None if not found or expired."""

    @abstractmethod
    async def put(
        self, key: str, value: dict[str, Any], ttl_seconds: float | None = None
    ) -> None:
        """Create or replace a document. Optional TTL in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a document. Returns True if it existed."""

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all non-expired keys, optionally filtered by prefix."""

    @abstractmethod
    async def query(
        self,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query non-expired documents with an optional filter function."""

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""


class FilePluginStore(PluginStore):
    """JSON key-value store backed by ``LocalBlobStore``.

    Each document stored as a JSON blob. No locks — uses atomic file writes.
    """

    def __init__(self, plugin_id: str, base_dir: Path | None = None) -> None:
        if base_dir is None:
            from hort.hort_config import hort_data_dir
            base_dir = hort_data_dir() / "plugins"
        from hort.ext.blobstore import LocalBlobStore
        self._blobs = LocalBlobStore(base_dir, plugin_id + ".data")

    async def _run(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    async def get(self, key: str) -> dict[str, Any] | None:
        return await self._run(self._blobs.get_json, key)

    async def put(
        self, key: str, value: dict[str, Any], ttl_seconds: float | None = None
    ) -> None:
        await self._run(self._blobs.put_json, key, value, ttl_seconds)

    async def delete(self, key: str) -> bool:
        return await self._run(self._blobs.delete, key)

    async def list_keys(self, prefix: str = "") -> list[str]:
        return await self._run(self._blobs.list_keys, prefix)

    async def query(
        self,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            for key in self._blobs.list_keys():
                value = self._blobs.get_json(key)
                if value is None:  # pragma: no cover
                    continue
                if filter_fn is None or filter_fn(value):
                    results.append(value)
                    if len(results) >= limit:
                        break
            return results
        return await self._run(_query)

    async def cleanup_expired(self) -> int:
        return await self._run(self._blobs.cleanup_expired)
