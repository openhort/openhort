"""Extension discovery, loading, and resolution."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import types as pytypes
from pathlib import Path
from typing import Any, TypeVar

from hort.ext.manifest import ExtensionManifest

T = TypeVar("T")
logger = logging.getLogger("hort.ext.registry")


class ExtensionRegistry:
    """Discovers, loads, and manages extensions and plugins.

    Typical lifecycle::

        registry = ExtensionRegistry()
        registry.discover(extensions_dir)
        registry.load_compatible()
        provider = registry.get_provider("window.list", WindowProvider)

    Enhanced llming support::

        registry.set_app(app)              # enable router mounting
        registry.load_compatible(config)   # injects Llming services
        registry.unload_extension("name")  # hot-unload
        registry.list_llmings()            # metadata for admin API
    """

    def __init__(self) -> None:
        self._manifests: list[ExtensionManifest] = []
        self._instances: dict[str, object] = {}  # ext name -> instance
        self._capability_map: dict[str, str] = {}  # capability -> ext name
        self._app: Any = None  # FastAPI app (set via set_app)

    def set_app(self, app: Any) -> None:
        """Set the FastAPI app for router mounting."""
        self._app = app

    # ----- Discovery -----

    def discover(self, extensions_dir: Path) -> list[ExtensionManifest]:
        """Scan *extensions_dir* for valid extensions.

        Expected layout::

            extensions_dir/
              <provider>/
                <extension_name>/
                  manifest.json

        Returns the list of discovered manifests (also stored internally).
        """
        manifests: list[ExtensionManifest] = []
        if not extensions_dir.is_dir():
            return manifests

        for provider_dir in sorted(extensions_dir.iterdir()):
            if not provider_dir.is_dir() or provider_dir.name.startswith("."):
                continue
            for ext_dir in sorted(provider_dir.iterdir()):
                if not ext_dir.is_dir() or ext_dir.name.startswith("."):
                    continue
                manifest_path = ext_dir / "manifest.json"
                if not manifest_path.exists():
                    continue
                manifest = _parse_manifest(manifest_path, ext_dir)
                if manifest is not None:
                    manifests.append(manifest)

        self._manifests = manifests
        return manifests

    # ----- Compatibility -----

    @staticmethod
    def is_compatible(manifest: ExtensionManifest) -> bool:
        """Check if *manifest* is compatible with the current platform."""
        return sys.platform in manifest.platforms

    # ----- Loading -----

    def load_extension(
        self,
        manifest: ExtensionManifest,
        config: dict[str, Any] | None = None,
    ) -> object | None:
        """Load and instantiate an extension from its manifest.

        For ``Llming`` instances, injects per-instance services
        (store, files, config, scheduler, logger) before calling activate.

        Returns the instance or ``None`` on failure.
        """
        if not manifest.entry_point or not manifest.path:
            return None

        ext_path = Path(manifest.path)
        module_name, _, class_name = manifest.entry_point.partition(":")
        if not class_name:
            return None

        module_file = ext_path / f"{module_name}.py"
        if not module_file.exists():
            return None

        module = _load_module(
            f"_hort_ext_{manifest.provider}_{manifest.name}_{module_name}",
            module_file,
        )
        if module is None:
            return None

        ext_class = getattr(module, class_name, None)
        if ext_class is None:
            return None

        instance: object = ext_class()

        # Inject services for Llming instances
        from hort.llming.base import Llming

        if isinstance(instance, Llming):
            self._inject_llming_services(instance, manifest, config or {})

        if hasattr(instance, "activate"):
            instance.activate(config or {})

        self._instances[manifest.name] = instance
        for cap in manifest.capabilities:
            if cap not in self._capability_map:
                self._capability_map[cap] = manifest.name

        # Mount router if available
        if self._app is not None and hasattr(instance, "get_router"):
            router = instance.get_router()
            if router:
                try:
                    self._app.include_router(
                        router, prefix=f"/api/llmings/{manifest.name}"
                    )
                    logger.info("Mounted router for %s", manifest.name)
                except Exception as e:
                    logger.warning("Failed to mount router for %s: %s", manifest.name, e)

        return instance

    def _inject_llming_services(
        self, instance: object, manifest: ExtensionManifest, config: dict[str, Any]
    ) -> None:
        """Inject per-instance services into a Llming instance."""
        from hort.ext.file_store import LocalFileStore
        from hort.ext.scheduler import PluginScheduler
        from hort.ext.store import FilePluginStore
        from hort.llming.base import Llming
        from hort.llming.bus import MessageBus
        from hort.llming.pulse import PulseBus

        if not isinstance(instance, Llming):
            return

        name = manifest.name
        from hort.hort_config import hort_data_dir
        base_dir = hort_data_dir() / "plugins"

        instance._instance_name = name
        instance._class_name = name
        instance._store = FilePluginStore(name, base_dir=base_dir)
        instance._files = LocalFileStore(name, base_dir=base_dir)
        instance._scheduler = PluginScheduler(name)
        instance._logger = logging.getLogger(f"hort.llming.{name}")
        instance._pulse_bus = PulseBus.get()
        instance._config = config

        # Load Soul from SOUL.md
        ext_path = Path(manifest.path) if manifest.path else None
        if ext_path:
            soul_path = ext_path / "SOUL.md"
            if soul_path.exists():
                instance._soul_text = soul_path.read_text()

        # Register on message bus
        MessageBus.get().register(name, instance)

    def load_compatible(
        self, config: dict[str, dict[str, Any]] | None = None
    ) -> None:
        """Load all platform-compatible discovered extensions.

        *config* is an optional mapping of ``{extension_name: ext_config}``.
        """
        cfg = config or {}
        for manifest in self._manifests:
            if not self.is_compatible(manifest):
                continue
            self.load_extension(manifest, cfg.get(manifest.name))

    # ----- Unloading -----

    def unload_extension(self, name: str) -> bool:
        """Hot-unload a plugin. Calls deactivate, removes routes.

        Scheduler cleanup for Llming instances is handled by
        ``stop_plugins()`` in ``hort/plugins.py``.

        Returns True if the extension was loaded and is now unloaded.
        """
        instance = self._instances.pop(name, None)
        if instance is None:
            return False

        # Call deactivate
        if hasattr(instance, "deactivate"):
            try:
                instance.deactivate()
            except Exception as e:
                logger.warning("Error deactivating %s: %s", name, e)

        # Remove from capability map
        self._capability_map = {
            cap: ext for cap, ext in self._capability_map.items() if ext != name
        }

        # Remove mounted routes (best effort)
        if self._app is not None:
            prefixes = (f"/api/llmings/{name}",)
            self._app.routes[:] = [
                r for r in self._app.routes
                if not (hasattr(r, "path") and r.path.startswith(prefixes))
            ]

        logger.info("Unloaded extension: %s", name)
        return True

    # ----- Provider resolution -----

    def get_provider(self, capability: str, provider_type: type[T]) -> T | None:
        """Get the loaded provider for *capability*, or ``None``.

        Returns the provider only if it is an instance of *provider_type*.
        """
        ext_name = self._capability_map.get(capability)
        if ext_name is None:
            return None
        instance = self._instances.get(ext_name)
        if instance is not None and isinstance(instance, provider_type):
            return instance
        return None

    # ----- Query -----

    def get_instance(self, name: str) -> object | None:
        """Get a loaded extension instance by name."""
        return self._instances.get(name)

    def get_manifest(self, name: str) -> ExtensionManifest | None:
        """Get a manifest by extension name."""
        for m in self._manifests:
            if m.name == name:
                return m
        return None

    def list_llmings(self) -> list[dict[str, Any]]:
        """Return metadata about all discovered llmings (for admin API)."""
        results: list[dict[str, Any]] = []
        for m in self._manifests:
            loaded = m.name in self._instances
            inst = self._instances.get(m.name)
            # Running jobs from the instance's scheduler (Llming)
            scheduler = getattr(inst, "_scheduler", None) if inst else None
            running_jobs = scheduler.running_jobs if scheduler else []
            results.append({
                "name": m.name,
                "provider": m.provider,
                "version": m.version,
                "description": m.description,
                "icon": m.icon,
                "llming_type": m.llming_type,
                "loaded": loaded,
                "compatible": self.is_compatible(m),
                "capabilities": list(m.capabilities),
                "features": {
                    name: {
                        "description": ft.description,
                        "default": ft.default,
                        "enabled": ft.default,
                    }
                    for name, ft in m.features.items()
                },
                "running_jobs": running_jobs,
                "ui_widgets": list(m.ui_widgets),
                "ui_script": m.ui_script,
                "auth_status": self._get_auth_status(m.name),
            })
        return results

    # Backward-compatible alias
    list_plugins = list_llmings

    def _get_auth_status(self, plugin_name: str) -> dict[str, Any] | None:
        """Get credential status for a plugin, or None if no auth configured."""
        inst = self._instances.get(plugin_name)
        if inst is None:
            return None
        # Check if plugin has a CredentialStore (via 'creds' attribute)
        creds = getattr(inst, "creds", None)
        if creds is None:
            return None
        from hort.ext.credentials import CredentialStore
        if isinstance(creds, CredentialStore):
            return creds.status_dict()
        return None


# ----- Helpers -----


def _parse_manifest(
    manifest_path: Path, ext_dir: Path
) -> ExtensionManifest | None:
    """Parse a ``manifest.json`` file, returning ``None`` on any error."""
    try:
        data: dict[str, Any] = json.loads(manifest_path.read_text())
        data["path"] = str(ext_dir)
        return ExtensionManifest(**data)
    except (json.JSONDecodeError, TypeError, Exception):
        return None


def _load_module(
    full_name: str, module_file: Path
) -> pytypes.ModuleType | None:
    """Load a Python module from *module_file* without polluting ``sys.path``."""
    spec = importlib.util.spec_from_file_location(full_name, module_file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
