"""Plugin base class and context — enhanced extension with injected services.

``PluginBase`` is a superset of ``ExtensionBase``. Old extensions that inherit
``ExtensionBase`` continue to work. New plugins inherit ``PluginBase`` and
get a ``PluginContext`` injected before ``activate()`` is called.

The context provides:
- ``store`` — per-plugin key-value data store (with TTL)
- ``files`` — per-plugin binary file storage (with deprecation)
- ``config`` — typed config with feature toggle access
- ``scheduler`` — interval job management
- ``shared_stores`` — cross-plugin stores granted by the user
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hort.ext.types import ExtensionBase

if TYPE_CHECKING:
    from hort.ext.file_store import PluginFileStore
    from hort.ext.scheduler import PluginScheduler
    from hort.ext.store import PluginStore


@dataclass
class PluginConfig:
    """Per-plugin configuration with feature toggle access.

    Wraps the raw config dict from ``ConfigStore`` and provides
    convenient access to feature toggles.
    """

    plugin_id: str
    _raw: dict[str, Any] = field(default_factory=dict)
    _feature_defaults: dict[str, bool] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value."""
        return self._raw.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value (in memory — call save() to persist)."""
        self._raw[key] = value

    @property
    def raw(self) -> dict[str, Any]:
        """Full raw config dict."""
        return self._raw

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a feature toggle is enabled.

        Priority: runtime override > config file > manifest default.
        """
        overrides = self._raw.get("_feature_overrides", {})
        if feature in overrides:
            return bool(overrides[feature])
        return self._feature_defaults.get(feature, True)

    def set_feature(self, feature: str, enabled: bool) -> None:
        """Override a feature toggle at runtime."""
        overrides = self._raw.setdefault("_feature_overrides", {})
        overrides[feature] = enabled


@dataclass
class PluginContext:
    """Injected into ``PluginBase`` instances by the registry.

    Provides sandboxed access to per-plugin services. A plugin cannot
    access another plugin's store or scheduler.
    """

    plugin_id: str
    store: PluginStore
    files: PluginFileStore
    config: PluginConfig
    scheduler: PluginScheduler
    logger: logging.Logger
    shared_stores: dict[str, PluginStore] = field(default_factory=dict)
    last_interaction: float = 0.0  # timestamp of last user interaction
    is_favorite: bool = False  # user-pinned to top of grid


class PluginBase(ExtensionBase):
    """Enhanced extension base with injected context.

    Inherits from ``ExtensionBase`` for backward compatibility.
    The registry detects ``PluginBase`` instances and injects a
    ``PluginContext`` before calling ``activate()``.

    Example::

        class MyPlugin(PluginBase):
            def activate(self, config: dict[str, Any]) -> None:
                self.log.info("Starting %s", self.plugin_id)

            async def do_work(self) -> None:
                await self.store.put("result", {"status": "ok"})
    """

    _ctx: PluginContext

    @property
    def plugin_id(self) -> str:
        """The plugin's unique ID from its manifest name."""
        return self._ctx.plugin_id

    @property
    def store(self) -> PluginStore:
        """Per-plugin namespaced key-value data store."""
        return self._ctx.store

    @property
    def files(self) -> PluginFileStore:
        """Per-plugin binary file storage."""
        return self._ctx.files

    @property
    def config(self) -> PluginConfig:
        """Per-plugin typed configuration with feature toggles."""
        return self._ctx.config

    @property
    def log(self) -> logging.Logger:
        """Plugin-scoped logger (hort.plugin.<id>)."""
        return self._ctx.logger

    @property
    def shared_stores(self) -> dict[str, PluginStore]:
        """Cross-plugin stores granted by the user."""
        return self._ctx.shared_stores
