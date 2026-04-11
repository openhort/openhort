"""Vault — a named storage space with shelves (scrolls) and holds (crates).

Each vault has metadata (group, description) and provides access
to its shelves and holds. Vaults are the organizational unit for
cross-llming access control.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from hort.storage.crates import CrateStore
from hort.storage.scrolls import ScrollStore

logger = logging.getLogger(__name__)


class Scope:
    """A filtered view of a shelf — named query that acts like a collection."""

    def __init__(self, shelf: ScrollStore, collection: str, filt: dict[str, Any]) -> None:
        self._shelf = shelf
        self._collection = collection
        self._filter = filt

    def find(self, extra_filter: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        merged = {**self._filter, **(extra_filter or {})}
        return self._shelf.find(self._collection, merged, **kwargs)

    def find_one(self, extra_filter: dict[str, Any] | None = None) -> dict[str, Any] | None:
        merged = {**self._filter, **(extra_filter or {})}
        return self._shelf.find_one(self._collection, merged)

    def count(self, extra_filter: dict[str, Any] | None = None) -> int:
        merged = {**self._filter, **(extra_filter or {})}
        return self._shelf.count(self._collection, merged)


class Shelf:
    """A named collection of scrolls within a vault.

    Wraps ScrollStore with a fixed collection name for convenience.
    """

    def __init__(self, store: ScrollStore, collection: str) -> None:
        self._store = store
        self._collection = collection

    def insert(self, scroll: dict[str, Any], ttl: int | None = None, access: str = "private") -> str:
        return self._store.insert(self._collection, scroll, ttl=ttl, access=access)

    def find_one(self, filt: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self._store.find_one(self._collection, filt)

    def find(self, filt: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        return self._store.find(self._collection, filt, **kwargs)

    def count(self, filt: dict[str, Any] | None = None) -> int:
        return self._store.count(self._collection, filt)

    def update_one(self, filt: dict[str, Any], update: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self._store.update_one(self._collection, filt, update, **kwargs)

    def update_many(self, filt: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        return self._store.update_many(self._collection, filt, update)

    def delete_one(self, filt: dict[str, Any]) -> dict[str, Any]:
        return self._store.delete_one(self._collection, filt)

    def delete_many(self, filt: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._store.delete_many(self._collection, filt)

    def scope(self, name: str, filt: dict[str, Any] | None = None) -> Scope:
        """Create a filtered view of this shelf."""
        return Scope(self._store, self._collection, filt or {})


class Hold:
    """A named container of crates within a vault.

    Wraps CrateStore with a fixed container name for convenience.
    """

    def __init__(self, store: CrateStore, container: str) -> None:
        self._store = store
        self._container = container

    def put(self, name: str, data: bytes, **kwargs: Any) -> Any:
        return self._store.put(self._container, name, data, **kwargs)

    def get(self, name: str) -> tuple[bytes, Any] | None:
        return self._store.get(self._container, name)

    def head(self, name: str) -> Any:
        return self._store.head(self._container, name)

    def list(self, prefix: str = "") -> list[Any]:
        return self._store.list(self._container, prefix)

    def delete(self, name: str) -> bool:
        return self._store.delete(self._container, name)

    def exists(self, name: str) -> bool:
        return self._store.exists(self._container, name)


class Vault:
    """A named storage space with shelves and holds.

    Usage::

        vault = self.persist.vault("metrics",
            group="public", description="System metrics")
        vault.shelf("cpu").insert({"value": 42.5})
        vault.hold("exports").put("report.pdf", data)
    """

    def __init__(
        self,
        name: str,
        scrolls: ScrollStore,
        crates: CrateStore,
        group: str = "private",
        description: str = "",
    ) -> None:
        self.name = name
        self.group = group
        self.description = description
        self._scrolls = scrolls
        self._crates = crates
        self._shelves: dict[str, Shelf] = {}
        self._holds: dict[str, Hold] = {}

    def shelf(self, name: str) -> Shelf:
        """Get a named shelf (collection of scrolls)."""
        if name not in self._shelves:
            # Prefix collection name with vault name for isolation
            collection = f"{self.name}/{name}"
            self._shelves[name] = Shelf(self._scrolls, collection)
        return self._shelves[name]

    def hold(self, name: str) -> Hold:
        """Get a named hold (container for crates)."""
        if name not in self._holds:
            container = f"{self.name}/{name}"
            self._holds[name] = Hold(self._crates, container)
        return self._holds[name]

    @property
    def meta(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group,
            "description": self.description,
        }
