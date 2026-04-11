"""LlmingRegistry — class/instance management for llmings.

Builds on top of the existing ExtensionRegistry for backward compatibility.
Adds the class/instance separation from the v2 architecture:

- **LlmingClass** — installed package (manifest, soul, credential specs, code).
  One per type. Discovered at startup from extension directories.

- **LlmingInstance** — running service (config, credentials, pulse, scheduler).
  Zero to many per type. Created from YAML config or at runtime.

The registry manages both and coordinates with the MessageBus and PulseBus.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hort.ext.manifest import ExtensionManifest
from hort.llming.base import LlmingBase
from hort.llming.bus import MessageBus
from hort.llming.pulse import PulseBus

logger = logging.getLogger(__name__)


@dataclass
class LlmingClass:
    """Installed llming type — one per extension.

    Contains everything needed to create instances: manifest, soul text,
    credential specs, and the Python class.
    """

    name: str                          # e.g. "office365", "system-monitor"
    manifest: ExtensionManifest
    python_class: type[LlmingBase]
    soul_text: str = ""                # loaded from SOUL.md
    credential_specs: list[dict[str, Any]] = field(default_factory=list)
    singleton: bool = False            # from manifest

    @property
    def path(self) -> Path:
        return Path(self.manifest.path)


@dataclass
class LlmingInstanceInfo:
    """Metadata about a running llming instance."""

    instance_name: str                 # e.g. "work-email"
    class_name: str                    # e.g. "office365"
    config: dict[str, Any] = field(default_factory=dict)
    credential_id: str = ""            # bound credential


class LlmingRegistry:
    """Manages llming classes and instances.

    The registry is the central point for:
    - Discovering llming classes from extension directories
    - Creating and managing llming instances
    - Coordinating with the MessageBus and PulseBus
    - Providing v1-compatible interfaces for the existing infrastructure

    Usage::

        registry = LlmingRegistry()
        registry.discover(extensions_dir)
        registry.create_instance("work-email", "office365", config={...})
        instance = registry.get_instance("work-email")
    """

    _instance: LlmingRegistry | None = None

    def __init__(self) -> None:
        self._classes: dict[str, LlmingClass] = {}
        self._instances: dict[str, LlmingBase] = {}
        self._instance_info: dict[str, LlmingInstanceInfo] = {}
        self._bus = MessageBus.get()
        self._pulse = PulseBus.get()

    @classmethod
    def get(cls) -> LlmingRegistry:
        """Get or create the singleton registry."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    # ── Class management ──

    def register_class(self, llming_class: LlmingClass) -> None:
        """Register a discovered llming class."""
        self._classes[llming_class.name] = llming_class

    def get_class(self, name: str) -> LlmingClass | None:
        """Look up a llming class by name."""
        return self._classes.get(name)

    def list_classes(self) -> list[LlmingClass]:
        """List all registered llming classes."""
        return list(self._classes.values())

    # ── Instance management ──

    def create_instance(
        self,
        instance_name: str,
        class_name: str,
        config: dict[str, Any] | None = None,
    ) -> LlmingBase | None:
        """Create and activate a llming instance.

        Returns the instance, or None if the class doesn't exist.
        """
        llming_class = self._classes.get(class_name)
        if llming_class is None:
            logger.warning("Unknown llming class: %s", class_name)
            return None

        # Singleton check
        if llming_class.singleton:
            for info in self._instance_info.values():
                if info.class_name == class_name:
                    logger.warning(
                        "Singleton %s already has instance %s",
                        class_name, info.instance_name,
                    )
                    return self._instances.get(info.instance_name)

        # Create instance
        instance = llming_class.python_class()
        instance._instance_name = instance_name
        instance._class_name = class_name
        instance._soul_text = llming_class.soul_text
        instance._pulse_bus = self._pulse
        instance._config = config or {}

        # Inject services
        self._inject_services(instance, llming_class)

        # Register on bus
        self._bus.register(instance_name, instance)

        # Activate
        instance.activate(config or {})

        # Store
        self._instances[instance_name] = instance
        self._instance_info[instance_name] = LlmingInstanceInfo(
            instance_name=instance_name,
            class_name=class_name,
            config=config or {},
        )

        # Start manifest-declared jobs
        self._start_manifest_jobs(instance, llming_class)

        logger.info("Created llming instance: %s (class=%s)", instance_name, class_name)
        return instance

    def get_instance(self, name: str) -> LlmingBase | None:
        """Look up a running llming instance."""
        return self._instances.get(name)

    def get_instance_info(self, name: str) -> LlmingInstanceInfo | None:
        """Get metadata about a running instance."""
        return self._instance_info.get(name)

    def list_instances(self) -> list[LlmingInstanceInfo]:
        """List all running instances."""
        return list(self._instance_info.values())

    def destroy_instance(self, name: str) -> bool:
        """Deactivate and remove an instance."""
        instance = self._instances.pop(name, None)
        if instance is None:
            return False

        # Stop scheduler
        if instance._scheduler is not None:
            instance._scheduler.stop_all()

        # Deactivate
        instance.deactivate()

        # Remove from bus and pulse
        self._bus.unregister(name)
        self._pulse.clear_instance(name)

        # Remove info
        self._instance_info.pop(name, None)

        logger.info("Destroyed llming instance: %s", name)
        return True

    # ── Discovery ──

    def discover(self, extensions_dir: Path) -> list[LlmingClass]:
        """Scan extensions directory for llming classes.

        Only discovers classes that inherit from LlmingBase.
        v1 PluginBase extensions are handled by the existing ExtensionRegistry.
        """
        import importlib.util

        discovered: list[LlmingClass] = []

        if not extensions_dir.is_dir():
            return discovered

        for provider_dir in sorted(extensions_dir.iterdir()):
            if not provider_dir.is_dir() or provider_dir.name.startswith("."):
                continue
            for ext_dir in sorted(provider_dir.iterdir()):
                if not ext_dir.is_dir() or ext_dir.name.startswith("."):
                    continue

                manifest_path = ext_dir / "manifest.json"
                if not manifest_path.exists():
                    continue

                try:
                    data = json.loads(manifest_path.read_text())
                    data["path"] = str(ext_dir)
                    manifest = ExtensionManifest(**data)
                except Exception:
                    continue

                if not manifest.entry_point:
                    continue

                module_name, _, class_name = manifest.entry_point.partition(":")
                if not class_name:
                    continue

                module_file = ext_dir / f"{module_name}.py"
                if not module_file.exists():
                    continue

                # Load module
                full_name = f"_hort_llming_{manifest.provider}_{manifest.name}_{module_name}"
                spec = importlib.util.spec_from_file_location(full_name, module_file)
                if spec is None or spec.loader is None:
                    continue

                try:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                except Exception:
                    continue

                ext_class = getattr(module, class_name, None)
                if ext_class is None:
                    continue

                # Only register LlmingBase subclasses
                if not (isinstance(ext_class, type) and issubclass(ext_class, LlmingBase)):
                    continue

                # Load Soul
                soul_text = ""
                soul_path = ext_dir / "SOUL.md"
                if soul_path.exists():
                    soul_text = soul_path.read_text()

                # Load credential specs
                cred_specs = data.get("credentials", [])

                llming_cls = LlmingClass(
                    name=manifest.name,
                    manifest=manifest,
                    python_class=ext_class,
                    soul_text=soul_text,
                    credential_specs=cred_specs,
                    singleton=data.get("singleton", False),
                )

                self.register_class(llming_cls)
                discovered.append(llming_cls)

        return discovered

    # ── Service injection ──

    def _inject_services(self, instance: LlmingBase, llming_class: LlmingClass) -> None:
        """Inject per-instance services into a LlmingBase instance."""
        from hort.ext.file_store import LocalFileStore
        from hort.ext.scheduler import PluginScheduler
        from hort.ext.store import FilePluginStore

        from hort.hort_config import hort_data_dir
        base_dir = hort_data_dir() / "plugins"
        name = instance._instance_name

        instance._store = FilePluginStore(name, base_dir=base_dir)
        instance._files = LocalFileStore(name, base_dir=base_dir)
        instance._scheduler = PluginScheduler(name)
        instance._logger = logging.getLogger(f"hort.llming.{name}")

    def _start_manifest_jobs(self, instance: LlmingBase, llming_class: LlmingClass) -> None:
        """Start jobs declared in the manifest."""
        from hort.ext.scheduler import JobSpec

        for job in llming_class.manifest.jobs:
            fn = getattr(instance, job.method, None)
            if fn is None:
                logger.warning(
                    "Job %s references missing method %s on %s",
                    job.id, job.method, instance._instance_name,
                )
                continue

            spec = JobSpec(
                id=job.id,
                fn_name=job.method,
                interval_seconds=job.interval_seconds,
                run_on_activate=job.run_on_activate,
                enabled_feature=job.enabled_feature,
            )
            instance.scheduler.start_job(spec, fn)

    # ── v1 compatibility ──

    def get_all_mcp_tools(self) -> list[tuple[str, dict[str, Any]]]:
        """Get all MCP tools from all instances. Returns (instance_name, tool_def) pairs."""
        tools: list[tuple[str, dict[str, Any]]] = []
        for name, instance in self._instances.items():
            for tool in instance.get_mcp_tools():
                tools.append((name, tool))
        return tools

    def get_all_connector_commands(self) -> list[tuple[str, dict[str, Any]]]:
        """Get all connector commands from all instances."""
        commands: list[tuple[str, dict[str, Any]]] = []
        for name, instance in self._instances.items():
            for cmd in instance.get_connector_commands():
                commands.append((name, cmd))
        return commands
