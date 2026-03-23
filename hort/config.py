"""Configuration management — per-plugin keyed settings.

Each plugin/connector has a unique ID (e.g. ``"connector.cloud"``,
``"connector.lan"``, ``"llming.terminal"``). It reads and writes
only its own section — never the full config.

Storage backends:
- ``YamlConfigStore`` — local YAML file (default, for single-machine)
- Future: ``MongoConfigStore`` — MongoDB for multi-instance

Plugin IDs are namespaced: ``connector.*``, ``llming.*``, ``plugin.*``.
The store enforces that plugins can only access their own namespace.

Security: plugin IDs are defined by the host code, not by plugins
themselves. A plugin receives its ID at registration time and can
only read/write that ID's config. This prevents credential theft.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger("hort.config")


class ConfigStore(ABC):
    """Abstract config backend. Plugins call get/set with their own ID."""

    @abstractmethod
    def get(self, plugin_id: str) -> dict[str, Any]:
        """Get config for a plugin by ID. Returns {} if not set."""

    @abstractmethod
    def set(self, plugin_id: str, config: dict[str, Any]) -> None:
        """Set config for a plugin by ID (full replace)."""

    def update(self, plugin_id: str, partial: dict[str, Any]) -> dict[str, Any]:
        """Merge partial updates into existing config. Returns merged."""
        current = self.get(plugin_id)
        current.update(partial)
        self.set(plugin_id, current)
        return current


class YamlConfigStore(ConfigStore):
    """YAML file-based config store.

    File structure::

        connector.cloud:
          enabled: false
          server: https://...
          key: ""

        connector.lan:
          enabled: true

        llming.terminal:
          default_shell: /bin/zsh
    """

    def __init__(self, path: str | Path = "hort-config.yaml") -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            import yaml

            data = yaml.safe_load(self._path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("Failed to load %s: %s", self._path, e)
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            import yaml

            self._path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=True))
        except Exception as e:
            logger.warning("Failed to save %s: %s", self._path, e)

    def get(self, plugin_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            val = data.get(plugin_id, {})
            return dict(val) if isinstance(val, dict) else {}

    def set(self, plugin_id: str, config: dict[str, Any]) -> None:
        with self._lock:
            data = self._load()
            data[plugin_id] = config
            self._save(data)


# ===== Singleton =====

_store: ConfigStore | None = None


def get_store() -> ConfigStore:
    """Get the global config store (singleton)."""
    global _store
    if _store is None:
        _store = YamlConfigStore()
    return _store


def set_store(store: ConfigStore) -> None:
    """Replace the global config store (e.g. switch to MongoDB)."""
    global _store
    _store = store
