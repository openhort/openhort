"""Host-side llming subprocess management.

LlmingProcess — ManagedProcess that spawns a llming runner subprocess.
LlmingProxy — Llming subclass that routes all calls over IPC.

The registry stores LlmingProxy instances. All existing code (WS commands,
MCP bridge, connector framework) works unchanged because LlmingProxy has
the same interface as Llming.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from hort.lifecycle.ipc_protocol import (
    PROTOCOL_VERSION,
    dict_to_power,
    msg_activate,
    msg_deactivate,
    msg_execute_power,
    msg_get_powers,
    msg_get_pulse,
    msg_viewer_connect,
    msg_viewer_disconnect,
)
from hort.lifecycle.manager import ManagedProcess
from hort.llming.base import Llming
from hort.llming.powers import Power

logger = logging.getLogger(__name__)


class LlmingProxy(Llming):
    """Drop-in Llming replacement that routes calls over IPC.

    The main process stores this in the registry. All existing code
    calls the same methods (get_pulse, execute_power, get_powers, etc.)
    but they go through IPC to the subprocess instead of running locally.

    Pulse data is cached and refreshed by the subprocess pushing updates.
    Powers are cached at registration time (they don't change).
    """

    def __init__(self, name: str, process: LlmingProcess) -> None:
        self._instance_name = name
        self._class_name = name
        self._process = process
        self._cached_powers: list[Power] = []
        self._cached_pulse: dict[str, Any] = {}
        self._ready = False

    def get_powers(self) -> list[Power]:
        return self._cached_powers

    def get_pulse(self) -> dict[str, Any]:
        return self._cached_pulse

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        result = await self._process.request(msg_execute_power(name, args))
        if isinstance(result, dict) and "error" in result:
            return result
        return result

    async def on_viewer_connect(self, session_id: str, controller: Any) -> None:
        await self._process.send_fire_and_forget(msg_viewer_connect(session_id))

    async def on_viewer_disconnect(self, session_id: str) -> None:
        await self._process.send_fire_and_forget(msg_viewer_disconnect(session_id))

    def activate(self, config: dict[str, Any]) -> None:
        # Activation is handled asynchronously after subprocess connects
        self._config = config

    def deactivate(self) -> None:
        # Handled by LlmingProcess.stop()
        pass

    # ── v1 compat ──

    @property
    def plugin_id(self) -> str:
        return self._instance_name

    def get_status(self) -> dict[str, Any]:
        return self._cached_pulse


class LlmingProcess(ManagedProcess):
    """Manages a llming subprocess and provides the proxy interface.

    Usage::

        proc = LlmingProcess("system-monitor", "/path/to/manifest.json")
        await proc.start()         # spawns subprocess, waits for ready
        proxy = proc.proxy         # drop-in Llming replacement
        pulse = proxy.get_pulse()  # returns cached data from subprocess
        result = await proxy.execute_power("get_metrics", {})  # IPC call
        await proc.stop()          # clean shutdown
    """

    protocol_version = PROTOCOL_VERSION

    def __init__(self, llming_name: str, manifest_path: str) -> None:
        super().__init__()
        self.name = f"llming-{llming_name}"
        self._llming_name = llming_name
        self._manifest_path = manifest_path
        self._proxy = LlmingProxy(llming_name, self)
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._ready_event = asyncio.Event()

    @property
    def proxy(self) -> LlmingProxy:
        return self._proxy

    def build_command(self) -> list[str]:
        return [
            sys.executable, "-m", "hort.lifecycle.runner",
            "--manifest", self._manifest_path,
        ]

    async def on_connected(self) -> None:
        logger.info("[%s] Subprocess connected", self.name)

    async def on_disconnected(self) -> None:
        logger.info("[%s] Subprocess disconnected", self.name)
        # Fail all pending requests
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Subprocess disconnected"))
        self._pending.clear()
        self._proxy._ready = False

    async def on_message(self, msg: dict[str, Any]) -> None:
        """Handle messages from the subprocess."""
        msg_type = msg.get("type", "")

        if msg_type == "result":
            self._resolve_pending(msg["id"], msg.get("value"))

        elif msg_type == "error":
            self._reject_pending(msg["id"], msg.get("error", "Unknown error"))

        elif msg_type == "register_powers":
            powers = [dict_to_power(d) for d in msg.get("powers", [])]
            self._proxy._cached_powers = powers
            logger.info("[%s] Registered %d powers", self.name, len(powers))

        elif msg_type == "pulse_update":
            self._proxy._cached_pulse = msg.get("data", {})

        elif msg_type == "pulse_emit":
            # Forward to the PulseBus
            try:
                from hort.llming.pulse import PulseBus
                bus = PulseBus.get()
                await bus.emit(self._llming_name, msg["event"], msg.get("data", {}))
            except Exception:
                pass

        elif msg_type == "log":
            level = msg.get("level", "info")
            message = msg.get("message", "")
            getattr(logger, level, logger.info)("[%s] %s", self.name, message)

        elif msg_type == "ready":
            self._proxy._ready = True
            self._ready_event.set()
            logger.info("[%s] Ready", self.name)

    async def activate(self, config: dict[str, Any]) -> None:
        """Send activate to the subprocess and wait for result."""
        self._proxy._config = config
        await self.request(msg_activate(config))

    async def wait_ready(self, timeout: float = 15.0) -> bool:
        """Wait for the subprocess to signal ready."""
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("[%s] Subprocess not ready after %.1fs", self.name, timeout)
            return False

    async def request(self, msg: dict[str, Any]) -> Any:
        """Send a request and wait for the response."""
        msg_id = msg["id"]
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[msg_id] = fut

        try:
            await self.send(msg)
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("[%s] Request %s timed out", self.name, msg.get("type"))
            return {"error": "timeout"}
        finally:
            self._pending.pop(msg_id, None)

    async def send_fire_and_forget(self, msg: dict[str, Any]) -> None:
        """Send a message without waiting for response."""
        try:
            await self.send(msg)
        except ConnectionError:
            pass

    def _resolve_pending(self, msg_id: str, value: Any) -> None:
        fut = self._pending.get(msg_id)
        if fut and not fut.done():
            fut.set_result(value)

    def _reject_pending(self, msg_id: str, error: str) -> None:
        fut = self._pending.get(msg_id)
        if fut and not fut.done():
            fut.set_exception(RuntimeError(error))
