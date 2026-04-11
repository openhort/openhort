"""Unified storage — the single API every llming uses for all data.

Every llming gets a ``Storage`` instance with two namespaces:

- ``runtime`` — ephemeral, dies with the process/container
- ``persist`` — on the host, survives everything

Each namespace provides vaults. Each vault has shelves (scrolls)
and holds (crates).

No other storage mechanisms. No direct filesystem access.
All data goes through scrolls, crates, or pulses.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from hort.storage.crates import CrateStore
from hort.storage.scrolls import ScrollStore
from hort.storage.vault import Vault

logger = logging.getLogger(__name__)

_GC_INTERVAL = 60  # seconds between garbage collection runs


class Namespace:
    """A storage namespace with scrolls + crates, organized into vaults."""

    def __init__(self, scrolls: ScrollStore, crates: CrateStore) -> None:
        self.scrolls = scrolls
        self.crates = crates
        self._vaults: dict[str, Vault] = {}

    def vault(self, name: str, group: str = "private", description: str = "") -> Vault:
        """Get or create a named vault."""
        if name not in self._vaults:
            self._vaults[name] = Vault(name, self.scrolls, self.crates, group, description)
        else:
            # Update metadata if provided
            v = self._vaults[name]
            if group != "private":
                v.group = group
            if description:
                v.description = description
        return self._vaults[name]

    def list_vaults(self) -> list[dict[str, Any]]:
        """List all vaults with metadata."""
        return [v.meta for v in self._vaults.values()]

    def gc(self) -> int:
        """Run garbage collection. Returns total items removed."""
        return self.scrolls.gc() + self.crates.gc()

    def close(self) -> None:
        self.scrolls.close()
        self.crates.close()


class Storage:
    """Per-llming storage with runtime + persist namespaces.

    Created by the framework and injected into the llming at activate.
    The llming never constructs this directly.
    """

    def __init__(self, llming_name: str, runtime_base: str | Path | None = None) -> None:
        from hort.paths import storage_dir, runtime_dir
        persist_base = storage_dir(llming_name)
        if runtime_base is None:
            runtime_base = runtime_dir(llming_name)

        persist_base = Path(persist_base)
        runtime_base = Path(runtime_base)

        self.persist = Namespace(
            scrolls=ScrollStore(persist_base / "scrolls.db"),
            crates=CrateStore(persist_base / "crates"),
        )
        self.runtime = Namespace(
            scrolls=ScrollStore(runtime_base / "scrolls.db"),
            crates=CrateStore(runtime_base / "crates"),
        )

        self._gc_thread: threading.Thread | None = None
        self._gc_running = False

    def start_gc(self) -> None:
        """Start periodic garbage collection in a background thread."""
        if self._gc_running:
            return
        self._gc_running = True
        self._gc_thread = threading.Thread(target=self._gc_loop, daemon=True)
        self._gc_thread.start()

    def stop_gc(self) -> None:
        self._gc_running = False

    def _gc_loop(self) -> None:
        import time
        while self._gc_running:
            time.sleep(_GC_INTERVAL)
            try:
                removed = self.runtime.gc() + self.persist.gc()
                if removed:
                    logger.info("Storage GC: removed %d expired items", removed)
            except Exception:
                pass

    def close(self) -> None:
        self._gc_running = False
        self.runtime.close()
        self.persist.close()


class StorageManager:
    """Manages Storage instances for all llmings.

    The server creates one StorageManager. Each llming gets its own
    isolated Storage via ``get(llming_name)``.
    """

    _instance: "StorageManager | None" = None

    def __init__(self) -> None:
        self._stores: dict[str, Storage] = {}

    @classmethod
    def get(cls) -> "StorageManager":
        if cls._instance is None:
            cls._instance = StorageManager()
        return cls._instance

    def get_storage(self, llming_name: str) -> Storage:
        """Get or create the Storage for a llming."""
        if llming_name not in self._stores:
            storage = Storage(llming_name)
            storage.start_gc()
            self._stores[llming_name] = storage
        return self._stores[llming_name]

    def list_vaults(self, llming_name: str) -> list[dict[str, Any]]:
        """List all vaults for a llming (for cross-llming access discovery)."""
        storage = self._stores.get(llming_name)
        if not storage:
            return []
        return storage.persist.list_vaults() + storage.runtime.list_vaults()

    def get_vault(self, llming_name: str, vault_name: str, lifetime: str = "persist") -> Vault | None:
        """Get a vault from another llming (for cross-llming access)."""
        storage = self._stores.get(llming_name)
        if not storage:
            return None
        ns = storage.persist if lifetime == "persist" else storage.runtime
        return ns._vaults.get(vault_name)

    def close_all(self) -> None:
        for store in self._stores.values():
            store.close()
        self._stores.clear()
