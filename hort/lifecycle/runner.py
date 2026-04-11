"""Llming subprocess runner — loads and hosts a single llming.

Usage::

    python -m hort.lifecycle.runner --manifest /path/to/manifest.json

The runner:
1. Connects to the main process via IPC (Unix socket)
2. Loads the llming class from its manifest
3. Injects services (store, scheduler, logger, etc.)
4. Handles IPC messages (activate, execute_power, get_pulse, ...)
5. Pushes events back (pulse_update, register_powers, log, ...)

The llming runs entirely in this subprocess. The main process
never imports llming code — it only communicates via IPC.
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
    msg_pulse_update,
    msg_ready,
    msg_register_powers,
    msg_result,
    power_to_dict,
)
from hort.lifecycle.worker import Worker

logger = logging.getLogger(__name__)


class LlmingRunner(Worker):
    """Subprocess that hosts a single llming instance."""

    name = "llming"
    protocol_version = PROTOCOL_VERSION

    def __init__(self, manifest_path: str) -> None:
        super().__init__()
        self._manifest_path = manifest_path
        self._manifest: dict[str, Any] = {}
        self._instance: Any = None  # Llming instance
        self._pulse_task: asyncio.Task[None] | None = None

    async def on_connected(self) -> None:
        """IPC connected — load the llming and register powers."""
        try:
            self._manifest = json.loads(Path(self._manifest_path).read_text())
            self._instance = self._load_llming()
            if self._instance is None:
                await self.send(msg_log("error", f"Failed to load llming from {self._manifest_path}"))
                return

            # Register powers
            powers = self._instance.get_powers()
            await self.send(msg_register_powers([power_to_dict(p) for p in powers]))

            # Signal ready
            await self.send(msg_ready())
            logger.info("Llming %s ready", self._manifest.get("name", "?"))

            # Start pulse push loop
            self._pulse_task = asyncio.create_task(self._pulse_loop())

        except Exception as exc:
            await self.send(msg_log("error", f"Startup failed: {exc}"))

    async def on_message(self, msg: dict[str, Any]) -> None:
        """Handle messages from the main process."""
        msg_type = msg.get("type", "")
        msg_id = msg.get("id", "")

        try:
            if msg_type == "activate":
                self._handle_activate(msg.get("config", {}))
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "deactivate":
                self._handle_deactivate()
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "execute_power":
                result = await self._handle_execute_power(
                    msg.get("name", ""), msg.get("args", {}),
                )
                await self.send(msg_result(msg_id, result))

            elif msg_type == "get_pulse":
                pulse = self._instance.get_pulse() if self._instance else {}
                await self.send(msg_result(msg_id, pulse))

            elif msg_type == "get_powers":
                powers = self._instance.get_powers() if self._instance else []
                await self.send(msg_result(msg_id, [power_to_dict(p) for p in powers]))

            elif msg_type == "viewer_connect":
                if self._instance:
                    await self._instance.on_viewer_connect(msg.get("session_id", ""), None)
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "viewer_disconnect":
                if self._instance:
                    await self._instance.on_viewer_disconnect(msg.get("session_id", ""))
                await self.send(msg_result(msg_id, {"ok": True}))

            elif msg_type == "set_credential":
                if self._instance:
                    if not hasattr(self._instance, "_credentials_mem"):
                        self._instance._credentials_mem = {}
                    self._instance._credentials_mem[msg["key"]] = msg["value"]
                await self.send(msg_result(msg_id, {"ok": True}))

        except Exception as exc:
            logger.exception("Error handling %s", msg_type)
            if msg_id:
                await self.send(msg_error(msg_id, str(exc)))

    async def on_disconnected(self) -> None:
        if self._pulse_task:
            self._pulse_task.cancel()
            self._pulse_task = None

    # ── Internal ──

    def _load_llming(self) -> Any:
        """Load the llming class from the manifest and instantiate it."""
        entry_point = self._manifest.get("entry_point", "")
        if not entry_point or ":" not in entry_point:
            return None

        module_name, class_name = entry_point.split(":", 1)
        ext_dir = Path(self._manifest_path).parent
        module_file = ext_dir / f"{module_name}.py"

        if not module_file.exists():
            logger.error("Module file not found: %s", module_file)
            return None

        # Load the module from file path (no package import needed)
        unique_name = f"_llming_{self._manifest.get('name', 'unknown')}_{module_name}"
        spec = importlib.util.spec_from_file_location(unique_name, module_file)
        if spec is None or spec.loader is None:
            return None

        # Add the extension directory to sys.path so relative imports work
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

        # Inject services
        self._inject_services(instance)

        return instance

    def _inject_services(self, instance: Any) -> None:
        """Inject per-instance services into the llming."""
        from hort.llming.base import Llming

        if not isinstance(instance, Llming):
            return

        name = self._manifest.get("name", "unknown")
        ext_dir = Path(self._manifest_path).parent

        instance._instance_name = name
        instance._class_name = name
        instance._config = {}
        instance._logger = logging.getLogger(f"hort.llming.{name}")

        # Storage — direct filesystem access to own data
        try:
            from hort.storage.store import StorageManager
            instance._storage = StorageManager.get().get_storage(name)
        except Exception:
            pass

        # Legacy stores
        try:
            from hort.hort_config import hort_data_dir
            from hort.ext.file_store import LocalFileStore
            from hort.ext.store import FilePluginStore

            base_dir = hort_data_dir() / "plugins"
            instance._store = FilePluginStore(name, base_dir=base_dir)
            instance._files = LocalFileStore(name, base_dir=base_dir)
        except Exception:
            pass

        # Scheduler
        try:
            from hort.ext.scheduler import PluginScheduler
            instance._scheduler = PluginScheduler(name)
        except Exception:
            pass

        # Load Soul from SOUL.md
        soul_path = ext_dir / "SOUL.md"
        if soul_path.exists():
            instance._soul_text = soul_path.read_text()

    def _handle_activate(self, config: dict[str, Any]) -> None:
        if self._instance:
            self._instance._config = config
            self._instance.activate(config)

    def _handle_deactivate(self) -> None:
        if self._instance:
            if self._instance._scheduler is not None:
                self._instance._scheduler.stop_all()
            self._instance.deactivate()

    async def _handle_execute_power(self, name: str, args: dict[str, Any]) -> Any:
        if not self._instance:
            return {"error": "No llming instance"}

        result = await self._instance.execute_power(name, args)

        # Ensure JSON-serializable
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return result

    async def _pulse_loop(self) -> None:
        """Periodically push pulse state to the main process."""
        while True:
            await asyncio.sleep(5)
            if not self._instance or not self._connected:
                continue
            try:
                pulse = self._instance.get_pulse()
                if pulse:
                    await self.send(msg_pulse_update(pulse))
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Llming subprocess runner")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    args = parser.parse_args()

    runner = LlmingRunner(args.manifest)
    runner.name = f"llming-{Path(args.manifest).parent.name}"
    runner.run()


if __name__ == "__main__":
    main()
