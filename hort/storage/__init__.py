"""Llming storage — scrolls + crates, runtime + persistent.

Every llming gets two isolated stores:

- **runtime** — ephemeral, dies with the process/container.
  Use for caches, temp files, session state. TTL auto-cleans.

- **persist** — on the host, survives restarts and container death.
  Use for circuits, user configs, conversation history, exports.
  Never lost.

Both stores expose the same API:

- **scrolls** — MongoDB-compatible document store (insert, find, update, delete)
- **crates** — Azure Blob-like file store (put, get, list, delete)

Usage from a llming::

    # Scrolls
    await self.persist.scrolls.insert("circuits", {"name": "my-flow", "nodes": [...]})
    flow = await self.persist.scrolls.find_one("circuits", {"name": "my-flow"})

    # Crates
    await self.persist.crates.put("exports", "screenshot.png", png_bytes, ttl=3600)
    data = await self.persist.crates.get("exports", "screenshot.png")

    # Runtime (ephemeral)
    await self.runtime.scrolls.insert("cache", {"key": "x", "value": 42}, ttl=300)
    await self.runtime.crates.put("tmp", "frame.webp", webp_bytes, ttl=60)
"""

from hort.storage.scrolls import ScrollStore
from hort.storage.crates import CrateStore, CrateInfo
from hort.storage.store import Storage, StorageManager
from hort.storage.vault import Vault, Shelf, Hold, Scope

__all__ = [
    "ScrollStore", "CrateStore", "CrateInfo",
    "Storage", "StorageManager",
    "Vault", "Shelf", "Hold", "Scope",
]
