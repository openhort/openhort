"""Llming — the unified base class for all llmings.

Five parts:
- **Soul** — what the llming knows (SOUL.md)
- **Powers** — what the llming can do (``@power`` decorator)
- **Pulse** — named channel events (``self.emit()``, ``self.channels``)
- **Cards** — how the llming looks (UI in cards.js)
- **Envoy** — where the llming executes remotely

Pythonic access to other llmings::

    await self.llmings["system-monitor"].call("get_metrics")
    await self.vaults["system-monitor"].read("latest_metrics")
    self.channels["cpu_spike"].subscribe(self.on_spike)

Vault (own data)::

    self.vault.set("state", {"connected": True})
    data = self.vault.get("state", default={})

Powers via decorators (no get_powers / execute_power needed)::

    @power("get_metrics", description="Get system metrics")
    async def get_metrics(self) -> MetricsResponse:
        return MetricsResponse(cpu=42.0)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from hort.llming.powers import Power, PowerType
from hort.llming.pulse import PulseBus

if TYPE_CHECKING:
    from hort.ext.file_store import PluginFileStore
    from hort.ext.scheduler import PluginScheduler
    from hort.ext.store import PluginStore
    from hort.llming.decorators import PowerMeta
    from hort.llming.handles import ChannelHandleMap, LlmingHandleMap, Vault, VaultHandleMap


class Llming:

    # ── Identity (set by the framework before activate) ──

    _instance_name: str = ""
    _class_name: str = ""

    # ── Soul (auto-loaded from SOUL.md by the framework) ──

    _soul_text: str = ""

    # ── Decorator-based power handlers (built by framework) ──

    _power_handlers: dict[str, tuple[Any, "PowerMeta"]]

    # ── Pythonic handles (injected by framework) ──

    vault: "Vault"                # self.vault.set("state", {...})
    llmings: "LlmingHandleMap"    # self.llmings["name"].call("power")
    vaults: "VaultHandleMap"      # self.vaults["name"].get("key")
    channels: "ChannelHandleMap"  # self.channels["name"].subscribe(handler)

    # ── Injected services ──

    _store: PluginStore | None = None        # legacy — use self.vault
    _files: PluginFileStore | None = None    # legacy — use self.persist.crates
    _storage: Any = None
    _scheduler: PluginScheduler | None = None
    _credentials: Any = None
    _logger: logging.Logger | None = None
    _pulse_bus: PulseBus | None = None
    _config: dict[str, Any] = {}

    # ── Identity properties ──

    @property
    def instance_name(self) -> str:
        """The instance name from YAML config (e.g. 'work-email')."""
        return self._instance_name

    @property
    def class_name(self) -> str:
        """The class name from manifest (e.g. 'office365')."""
        return self._class_name

    # ── Lifecycle ──

    def activate(self, config: dict[str, Any]) -> None:
        """Called once when the instance is loaded.

        Override to initialize instance state. All services (store,
        scheduler, credentials, etc.) are available at this point.
        """

    def deactivate(self) -> None:
        """Called when the instance is unloaded (shutdown / hot-reload).

        Override to clean up resources. The framework automatically
        stops the scheduler and clears pulse subscriptions.
        """

    async def on_viewer_connect(self, session_id: str, controller: Any) -> None:
        """Called when a viewer's WebSocket connects.

        Override to prepare data, push initial state, or start
        viewer-specific resources. Called for every llming on every
        viewer connect.
        """

    async def on_viewer_disconnect(self, session_id: str) -> None:
        """Called when a viewer's WebSocket disconnects.

        Override to clean up viewer-specific resources.
        """

    # ── Soul ──

    @property
    def soul(self) -> str:
        """Return Soul text (auto-loaded from SOUL.md by the framework)."""
        return self._soul_text

    # ── Powers ──

    def _build_power_map(self) -> None:
        """Collect @power-decorated methods. Called once by the framework."""
        from hort.llming.decorators import collect_powers
        self._power_handlers = collect_powers(self)

    def get_powers(self) -> list[Power]:
        """Return all powers (decorators + manual override).

        New-style: use @power decorators, don't override this.
        Old-style: override this to return a manual list.
        """
        powers: list[Power] = []
        for _handler, meta in getattr(self, "_power_handlers", {}).values():
            ptype = PowerType.COMMAND if meta.command else (PowerType.MCP if meta.mcp else PowerType.ACTION)
            powers.append(Power(
                name=meta.name,
                type=ptype,
                description=meta.description,
                input_schema=meta.input_model or {"type": "object", "properties": {}},
                output_schema=meta.output_model,
                admin_only=meta.admin_only,
            ))
        return powers

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        """Execute a power by name. Routes to @power handlers automatically.

        New-style: don't override. Decorators handle routing.
        Old-style: override for manual dispatch.
        """
        handlers = getattr(self, "_power_handlers", {})
        entry = handlers.get(name)
        if entry is not None:
            from hort.llming.decorators import invoke_handler
            handler, meta = entry
            return await invoke_handler(handler, meta, args)
        return {"error": f"Power {name} not implemented"}

    # ── Named channel events ──

    async def emit(self, channel: str, data: dict[str, Any] | BaseModel) -> None:
        """Emit an event on a named channel.

        The framework automatically injects ``_source`` (instance name)
        and ``_channel`` (channel name) into the payload so subscribers
        always know where an event came from.

        ::
            await self.emit("cpu_spike", CpuSpike(cpu=95, threshold=90))
            # Subscriber receives: {"cpu": 95, "threshold": 90, "_source": "system-monitor", "_channel": "cpu_spike"}
        """
        if self._pulse_bus is None:
            return
        payload = data.model_dump() if isinstance(data, BaseModel) else dict(data)
        payload["_source"] = self._instance_name
        payload["_channel"] = channel
        await self._pulse_bus.emit(self._instance_name, channel, payload)

    # ── Legacy pulse compat ──

    async def emit_pulse(self, event: str, data: dict[str, Any]) -> None:
        """Legacy. Use ``self.emit()`` instead."""
        await self.emit(event, data)

    def get_pulse_channels(self) -> list[str]:
        """Legacy. Channels are now in manifest.json ``publishes``."""
        return []

    def subscribe(self, target: str, event: str, handler: Any) -> None:
        """Legacy. Use ``self.channels[name].subscribe()`` instead."""
        if self._pulse_bus is not None:
            self._pulse_bus.subscribe(target, event, handler)

    def unsubscribe(self, target: str, event: str) -> None:
        """Legacy."""
        if self._pulse_bus is not None:
            self._pulse_bus.unsubscribe(target, event)

    # ── Built-in services (no mixins needed) ──

    @property
    def scheduler(self) -> PluginScheduler:
        """Built-in job scheduler."""
        assert self._scheduler is not None, "Scheduler not injected"
        return self._scheduler

    @property
    def store(self) -> PluginStore:
        """Legacy key-value store. Prefer self.persist.scrolls / self.runtime.scrolls."""
        assert self._store is not None, "Store not injected"
        return self._store

    @property
    def files(self) -> PluginFileStore:
        """Legacy file store. Prefer self.persist.crates / self.runtime.crates."""
        assert self._files is not None, "FileStore not injected"
        return self._files

    @property
    def persist(self) -> Any:
        """Persistent storage (survives restarts). Has .scrolls and .crates."""
        if self._storage is None:
            from hort.storage.store import StorageManager
            self._storage = StorageManager.get().get_storage(self._instance_name or self._class_name)
        return self._storage.persist

    @property
    def runtime(self) -> Any:
        """Runtime storage (ephemeral, dies with process). Has .scrolls and .crates."""
        if self._storage is None:
            from hort.storage.store import StorageManager
            self._storage = StorageManager.get().get_storage(self._instance_name or self._class_name)
        return self._storage.runtime

    @property
    def credentials(self) -> Any:
        """Scoped credential access for this instance."""
        return self._credentials

    # ── Discovery ──

    async def discover(self, target: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Discover available powers from other llmings.

        ::
            catalog = await self.discover("system-monitor")
            all_powers = await self.discover()
        """
        from hort.llming.bus import MessageBus
        catalog = MessageBus.get().power_catalog()
        if target:
            return {target: catalog.get(target, [])}
        return catalog

    @property
    def log(self) -> logging.Logger:
        """Instance-scoped logger (hort.llming.<instance_name>)."""
        if self._logger is None:
            self._logger = logging.getLogger(
                f"hort.llming.{self._instance_name or 'unknown'}"
            )
        return self._logger

    @property
    def config(self) -> dict[str, Any]:
        """Instance configuration from YAML."""
        return self._config

    # ── Compatibility bridge ──
    # These methods let Llming work with the existing v1 infrastructure
    # (ext/registry.py, MCP server, connector framework) during migration.

    def get_mcp_tools(self) -> list[Any]:
        """v1 compat: Return MCPToolDef objects for the MCP bridge."""
        from hort.ext.mcp import MCPToolDef

        result = []
        for p in self.get_powers():
            if p.type in (PowerType.MCP, PowerType.ACTION):
                tool_def = p.to_mcp_tool_def()
                result.append(MCPToolDef(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    input_schema=tool_def["inputSchema"],
                ))
        return result

    async def execute_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """v1 compat: Execute an MCP tool call. Returns MCPToolResult."""
        from hort.ext.mcp import MCPToolResult

        result = await self.execute_power(tool_name, arguments)

        # Already an MCPToolResult — pass through
        if isinstance(result, MCPToolResult):
            return result

        # Dict with "content" key — wrap as MCPToolResult
        if isinstance(result, dict) and "content" in result:
            return MCPToolResult(
                content=result["content"],
                is_error=result.get("is_error", False),
            )

        # Dict with "error" key
        if isinstance(result, dict) and "error" in result:
            return MCPToolResult(
                content=[{"type": "text", "text": result["error"]}],
                is_error=True,
            )

        # String result — wrap as text content
        if isinstance(result, str):
            return MCPToolResult(content=[{"type": "text", "text": result}])

        # Pydantic model result — serialize to JSON text
        from pydantic import BaseModel
        if isinstance(result, BaseModel):
            return MCPToolResult(content=[{"type": "text", "text": result.model_dump_json()}])

        # Fallback — stringify
        return MCPToolResult(content=[{"type": "text", "text": str(result)}])

    def get_connector_commands(self) -> list[Any]:
        """v1 compat: Return connector command definitions."""
        from hort.ext.connectors import ConnectorCommand

        return [
            ConnectorCommand(
                name=p.name,
                description=p.description,
                plugin_id=self._instance_name or self._class_name,
            )
            for p in self.get_powers()
            if p.type == PowerType.COMMAND
        ]

    async def handle_connector_command(
        self, command: str, message: Any, capabilities: Any
    ) -> Any:
        """v1 compat: Handle a connector command by routing to execute_power().

        The connector framework calls this with (command, IncomingMessage, ConnectorCapabilities).
        We route to execute_power() and wrap the result in a ConnectorResponse.
        """
        from hort.ext.connectors import ConnectorResponse

        result = await self.execute_power(command, {"args": message.command_args if message else ""})
        if result is None:
            return None
        if isinstance(result, str):
            return ConnectorResponse.simple(result)
        # If it's already a ConnectorResponse, pass through
        if hasattr(result, "text"):
            return result
        # Dict result — extract text
        if isinstance(result, dict) and "error" in result:
            return ConnectorResponse.simple(f"Error: {result['error']}")
        return ConnectorResponse.simple(str(result))

    @property
    def plugin_id(self) -> str:
        """v1 compat: Return instance name as plugin_id for the MCP bridge."""
        return self._instance_name or self._class_name

    def get_status(self) -> dict[str, Any]:
        """v1 compat: Read state from own vault."""
        return self.vault.get("state") if hasattr(self, "vault") else {}

    def get_jobs(self) -> list[Any]:
        """v1 compat: Return scheduled job definitions.

        Override this if you need scheduled jobs. Jobs are declared
        in the manifest's ``jobs`` array, not in code.
        """
        return []
