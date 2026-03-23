"""Plugin data store — per-plugin namespaced key-value storage with TTL.

Each plugin gets its own isolated store via ``PluginContext.store``.
Two backends:

- ``FilePluginStore`` — JSON file per plugin (default, single-machine)
- ``MongoPluginStore`` — MongoDB collection per plugin (multi-instance)

Values are dicts. Keys are strings. Optional TTL auto-expires entries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
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
    """JSON file-based plugin store.

    Data stored at ``{base_dir}/{plugin_id}/data.json``.
    Each entry is ``{key: {"_value": {...}, "_expires": float|null}}``.
    Thread-safe via asyncio.Lock. All file I/O via executor.
    """

    def __init__(self, plugin_id: str, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path("~/.hort/plugins").expanduser()
        self._path = base_dir / plugin_id / "data.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load_sync(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_sync(self, data: dict[str, Any]) -> None:
        self._path.write_text(json.dumps(data, indent=2))

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        expires = entry.get("_expires")
        return expires is not None and time.time() > expires

    async def _run(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    async def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            data = await self._run(self._load_sync)
            entry = data.get(key)
            if entry is None:
                return None
            if self._is_expired(entry):
                del data[key]
                await self._run(self._save_sync, data)
                return None
            return dict(entry.get("_value", {}))

    async def put(
        self, key: str, value: dict[str, Any], ttl_seconds: float | None = None
    ) -> None:
        with self._lock:
            data = await self._run(self._load_sync)
            entry: dict[str, Any] = {"_value": value, "_expires": None}
            if ttl_seconds is not None:
                entry["_expires"] = time.time() + ttl_seconds
            data[key] = entry
            await self._run(self._save_sync, data)

    async def delete(self, key: str) -> bool:
        with self._lock:
            data = await self._run(self._load_sync)
            if key not in data:
                return False
            del data[key]
            await self._run(self._save_sync, data)
            return True

    async def list_keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            data = await self._run(self._load_sync)
            now = time.time()
            return [
                k
                for k, v in data.items()
                if k.startswith(prefix) and not self._is_expired(v)
            ]

    async def query(
        self,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            data = await self._run(self._load_sync)
            results: list[dict[str, Any]] = []
            for entry in data.values():
                if self._is_expired(entry):
                    continue
                value = entry.get("_value", {})
                if filter_fn is None or filter_fn(value):
                    results.append(dict(value))
                    if len(results) >= limit:
                        break
            return results

    async def cleanup_expired(self) -> int:
        with self._lock:
            data = await self._run(self._load_sync)
            before = len(data)
            data = {k: v for k, v in data.items() if not self._is_expired(v)}
            after = len(data)
            removed = before - after
            if removed > 0:
                await self._run(self._save_sync, data)
            return removed
