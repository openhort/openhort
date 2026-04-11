"""Llming subprocess runner — loads a group of llmings in one process.

Usage::

    python -m hort.lifecycle.runner --manifests /path/a/manifest.json,/path/b/manifest.json
    python -m hort.lifecycle.runner --manifest /path/to/manifest.json  # single llming

The runner:
1. Connects to the main process via IPC (Unix socket)
2. Loads all llmings from their manifests
3. Injects services (store, scheduler, logger, etc.)
4. Handles IPC messages routed by llming name
5. Pushes events back (register_powers, pulse_update, log, ...)

All llmings in a group share this process — they can call each
other directly (same memory space). Cross-group communication
goes through IPC to the main process.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

from hort.lifecycle.ipc_protocol import (
    PROTOCOL_VERSION,
    msg_error,
    msg_log,
    msg_ready,
    msg_register_powers,
    msg_result,
    power_to_dict,
)
from hort.lifecycle.worker import Worker

logger = logging.getLogger(__name__)


class GroupRunner(Worker):
    """Subprocess that hosts one or more llmings (a group)."""

    name = "llming-group"
    protocol_version = PROTOCOL_VERSION

    def __init__(self, manifest_paths: list[str]) -> None:
        super().__init__()
        self._manifest_paths = manifest_paths
        self._instances: dict[str, Any] = {}  # {llming_name: Llming instance}
        self._manifests: dict[str, dict[str, Any]] = {}  # {name: manifest dict}

    async def on_connected(self) -> None:
        """IPC connected — load all llmings and register powers."""
        for path in self._manifest_paths:
            try:
                manifest = json.loads(Path(path).read_text())
                name = manifest.get("name", Path(path).parent.name)
                self._manifests[name] = manifest

                instance = self._load_llming(manifest, path)
                if instance is None:
                    await self.send(msg_log("error", f"Failed to load {name}"))
                    continue

                self._instances[name] = instance

                # Build @power handler map
                instance._build_power_map()

                # Register powers for this llming
                powers = instance.get_powers()
                await self.send(msg_register_powers(
                    [power_to_dict(p) for p in powers],
                    llming=name,
                ))

                logger.info("Loaded %s", name)

            except Exception as exc:
                await self.send(msg_log("error", f"Failed to load from {path}: {exc}"))

        await self.send(msg_ready())
        logger.info("Group ready: %s", list(self._instances.keys()))

    async def on_message(self, msg: dict[str, Any]) -> None:
        """Handle messages from main. Routes by `llming` field."""
        msg_type = msg.get("type", "")
        msg_id = msg.get("id", "")
        llming_name = msg.get("llming", "")

        # Find target instance
        inst = self._instances.get(llming_name)

        try:
            if msg_type == "activate":
                if inst:
                    inst._config = msg.get("config", {})
                    inst.activate(msg.get("config", {}))
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "deactivate":
                if inst:
                    if inst._scheduler is not None:
                        inst._scheduler.stop_all()
                    inst.deactivate()
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "execute_power":
                if not inst:
                    await self.send(msg_error(msg_id, f"Llming '{llming_name}' not found"))
                    return
                result = await inst.execute_power(msg.get("name", ""), msg.get("args", {}))
                if hasattr(result, "model_dump"):
                    result = result.model_dump()
                await self.send(msg_result(msg_id, result))

            elif msg_type == "get_powers":
                powers = inst.get_powers() if inst else []
                await self.send(msg_result(msg_id, [power_to_dict(p) for p in powers]))

            elif msg_type == "viewer_connect":
                for instance in self._instances.values():
                    await instance.on_viewer_connect(msg.get("session_id", ""), None)
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "viewer_disconnect":
                for instance in self._instances.values():
                    await instance.on_viewer_disconnect(msg.get("session_id", ""))
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "set_credential":
                if inst:
                    if not hasattr(inst, "_credentials_mem"):
                        inst._credentials_mem = {}
                    inst._credentials_mem[msg["key"]] = msg["value"]
                await self.send(msg_result(msg_id, {"ok": True}))

        except Exception as exc:
            logger.exception("Error handling %s for %s", msg_type, llming_name)
            if msg_id:
                await self.send(msg_error(msg_id, str(exc)))

    async def on_disconnected(self) -> None:
        pass

    # ── Internal ──

    def _load_llming(self, manifest: dict[str, Any], manifest_path: str) -> Any:
        """Load a llming class from its manifest and instantiate it."""
        entry_point = manifest.get("entry_point", "")
        if not entry_point or ":" not in entry_point:
            return None

        module_name, class_name = entry_point.split(":", 1)
        ext_dir = Path(manifest_path).parent
        module_file = ext_dir / f"{module_name}.py"

        if not module_file.exists():
            logger.error("Module file not found: %s", module_file)
            return None

        name = manifest.get("name", "unknown")
        unique_name = f"_llming_{name}_{module_name}"
        spec = importlib.util.spec_from_file_location(unique_name, module_file)
        if spec is None or spec.loader is None:
            return None

        ext_dir_str = str(ext_dir)
        if ext_dir_str not in sys.path:
            sys.path.insert(0, ext_dir_str)

        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        spec.loader.exec_module(module)

        ext_class = getattr(module, class_name, None)
        if ext_class is None:
            logger.error("Class %s not found in %s", class_name, module_file)
            return None

        instance = ext_class()
        self._inject_services(instance, manifest, ext_dir)
        return instance

    def _inject_services(self, instance: Any, manifest: dict[str, Any], ext_dir: Path) -> None:
        """Inject per-instance services into a llming."""
        from hort.llming.base import Llming

        if not isinstance(instance, Llming):
            return

        name = manifest.get("name", "unknown")

        instance._instance_name = name
        instance._class_name = name
        instance._config = {}
        instance._logger = logging.getLogger(f"hort.llming.{name}")

        try:
            from hort.storage.store import StorageManager
            instance._storage = StorageManager.get().get_storage(name)
        except Exception:
            pass

        try:
            from hort.hort_config import hort_data_dir
            from hort.ext.file_store import LocalFileStore
            from hort.ext.store import FilePluginStore

            base_dir = hort_data_dir() / "plugins"
            instance._store = FilePluginStore(name, base_dir=base_dir)
            instance._files = LocalFileStore(name, base_dir=base_dir)
        except Exception:
            pass

        try:
            from hort.ext.scheduler import PluginScheduler
            instance._scheduler = PluginScheduler(name)
        except Exception:
            pass

        soul_path = ext_dir / "SOUL.md"
        if soul_path.exists():
            instance._soul_text = soul_path.read_text()


def main() -> None:
    parser = argparse.ArgumentParser(description="Llming group subprocess runner")
    parser.add_argument("--manifests", help="Comma-separated manifest paths")
    parser.add_argument("--manifest", help="Single manifest path (backward compat)")
    args = parser.parse_args()

    if args.manifests:
        paths = [p.strip() for p in args.manifests.split(",") if p.strip()]
    elif args.manifest:
        paths = [args.manifest]
    else:
        parser.error("Either --manifests or --manifest required")
        return

    runner = GroupRunner(paths)
    # Name from group or single llming
    if len(paths) == 1:
        runner.name = f"llming-{Path(paths[0]).parent.name}"
    else:
        # Use group name from first manifest
        try:
            m = json.loads(Path(paths[0]).read_text())
            runner.name = f"group-{m.get('group', 'unnamed')}"
        except Exception:
            runner.name = "group-unnamed"
    runner.run()


if __name__ == "__main__":
    main()
