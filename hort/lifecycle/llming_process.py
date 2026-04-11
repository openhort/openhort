"""Host-side llming group process management.

GroupProcess — ManagedProcess that spawns a runner subprocess for a group.
LlmingProxy — Llming subclass that routes calls over IPC.

A group contains one or more llmings sharing a subprocess. Each llming
gets its own LlmingProxy. The registry stores proxies as if they were
regular Llming instances — all existing code works unchanged.

Single-llming groups (ungrouped llmings) work identically — they're
just groups of one.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from hort.lifecycle.ipc_protocol import (
    PROTOCOL_VERSION,
    dict_to_power,
    msg_activate,
    msg_execute_power,
    msg_viewer_connect,
    msg_viewer_disconnect,
)
from hort.lifecycle.manager import ManagedProcess
from hort.llming.base import Llming
from hort.llming.powers import Power

logger = logging.getLogger(__name__)


class LlmingProxy(Llming):
    """Drop-in Llming replacement that routes calls over IPC.

    The registry stores these. All existing code (WS commands, MCP bridge)
    calls the same methods but they go through IPC to the subprocess.
    """

    def __init__(self, name: str, process: GroupProcess) -> None:
        self._instance_name = name
        self._class_name = name
        self._process = process
        self._cached_powers: list[Power] = []
        self._ready = False

    def get_powers(self) -> list[Power]:
        return self._cached_powers

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        return await self._process.request(
            msg_execute_power(name, args, llming=self._instance_name),
        )

    async def on_viewer_connect(self, session_id: str, controller: Any) -> None:
        await self._process.send_fire_and_forget(msg_viewer_connect(session_id))

    async def on_viewer_disconnect(self, session_id: str) -> None:
        await self._process.send_fire_and_forget(msg_viewer_disconnect(session_id))

    def activate(self, config: dict[str, Any]) -> None:
        self._config = config

    def deactivate(self) -> None:
        pass

    @property
    def plugin_id(self) -> str:
        return self._instance_name

    def get_status(self) -> dict[str, Any]:
        return self.vault.get("state") if hasattr(self, "vault") else {}


class GroupProcess(ManagedProcess):
    """Manages a subprocess hosting one or more llmings (a group).

    Usage::

        proc = GroupProcess("core.systeminfo", {
            "system-monitor": "/path/to/manifest.json",
            "disk-usage": "/path/to/manifest.json",
        })
        await proc.start()
        proxy = proc.proxies["system-monitor"]
    """

    protocol_version = PROTOCOL_VERSION

    def __init__(self, group_name: str, manifest_paths: dict[str, str]) -> None:
        super().__init__()
        self.name = f"group-{group_name}" if group_name else f"llming-{next(iter(manifest_paths))}"
        self._group_name = group_name
        self._manifest_paths = manifest_paths
        self._proxies: dict[str, LlmingProxy] = {
            name: LlmingProxy(name, self) for name in manifest_paths
        }
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._ready_event = asyncio.Event()

    @property
    def proxies(self) -> dict[str, LlmingProxy]:
        return self._proxies

    def build_command(self) -> list[str]:
        paths = ",".join(self._manifest_paths.values())
        return [sys.executable, "-m", "hort.lifecycle.runner", "--manifests", paths]

    async def on_connected(self) -> None:
        logger.info("[%s] Connected (%d llmings)", self.name, len(self._manifest_paths))

    async def on_disconnected(self) -> None:
        logger.info("[%s] Disconnected", self.name)
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Subprocess disconnected"))
        self._pending.clear()
        for proxy in self._proxies.values():
            proxy._ready = False

    async def on_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type", "")

        if msg_type == "result":
            self._resolve_pending(msg["id"], msg.get("value"))

        elif msg_type == "error":
            self._reject_pending(msg["id"], msg.get("error", "Unknown error"))

        elif msg_type == "register_powers":
            llming_name = msg.get("llming", "")
            proxy = self._proxies.get(llming_name)
            if proxy:
                powers = [dict_to_power(d) for d in msg.get("powers", [])]
                proxy._cached_powers = powers
                logger.info("[%s] %s: %d powers", self.name, llming_name, len(powers))

        elif msg_type == "pulse_emit":
            try:
                from hort.llming.pulse import PulseBus
                await PulseBus.get().emit(msg.get("llming", ""), msg["event"], msg.get("data", {}))
            except Exception:
                pass

        elif msg_type == "log":
            level = msg.get("level", "info")
            getattr(logger, level, logger.info)("[%s] %s", self.name, msg.get("message", ""))

        elif msg_type == "ready":
            for proxy in self._proxies.values():
                proxy._ready = True
            self._ready_event.set()
            logger.info("[%s] Ready", self.name)

    async def activate_llming(self, name: str, config: dict[str, Any]) -> None:
        proxy = self._proxies.get(name)
        if proxy:
            proxy._config = config
        await self.request(msg_activate(config, llming=name))

    async def wait_ready(self, timeout: float = 15.0) -> bool:
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("[%s] Not ready after %.1fs", self.name, timeout)
            return False

    async def request(self, msg: dict[str, Any]) -> Any:
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


# Backward compat alias
LlmingProcess = GroupProcess
