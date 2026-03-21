"""Extension discovery, loading, and resolution."""

from __future__ import annotations

import importlib.util
import json
import sys
import types as pytypes
from pathlib import Path
from typing import Any, TypeVar

from hort.ext.manifest import ExtensionManifest

T = TypeVar("T")


class ExtensionRegistry:
    """Discovers, loads, and manages extensions.

    Typical lifecycle::

        registry = ExtensionRegistry()
        registry.discover(extensions_dir)
        registry.load_compatible()
        provider = registry.get_provider("window.list", WindowProvider)
    """

    def __init__(self) -> None:
        self._manifests: list[ExtensionManifest] = []
        self._instances: dict[str, object] = {}  # ext name -> instance
        self._capability_map: dict[str, str] = {}  # capability -> ext name

    # ----- Discovery -----

    def discover(self, extensions_dir: Path) -> list[ExtensionManifest]:
        """Scan *extensions_dir* for valid extensions.

        Expected layout::

            extensions_dir/
              <provider>/
                <extension_name>/
                  extension.json

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
                manifest_path = ext_dir / "extension.json"
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

        If *config* is not ``None`` and the instance has an ``activate``
        method, it will be called with the config dict.

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

        if config is not None and hasattr(instance, "activate"):
            instance.activate(config)

        self._instances[manifest.name] = instance
        for cap in manifest.capabilities:
            if cap not in self._capability_map:
                self._capability_map[cap] = manifest.name

        return instance

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


# ----- Helpers -----


def _parse_manifest(
    manifest_path: Path, ext_dir: Path
) -> ExtensionManifest | None:
    """Parse an ``extension.json`` file, returning ``None`` on any error."""
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
