"""Llming — the unified base class for all llmings. No mixins.

Replaces the v1 hierarchy of PluginBase + MCPMixin + ConnectorMixin +
ScheduledMixin + DocumentMixin with a single class that has standardized
interfaces for all five parts:

- **Soul** — what the llming knows (auto-loaded from SOUL.md)
- **Powers** — what the llming can do (MCP tools, commands, actions)
- **Pulse** — what the llming radiates (live state + events)
- **Cards** — how the llming looks (UI in cards.js)
- **Envoy** — where the llming executes remotely (YAML config)

Built-in services (no mixins needed):
- ``self.scheduler`` — interval job management
- ``self.store`` — per-instance key-value data store
- ``self.files`` — per-instance binary file storage
- ``self.credentials`` — scoped credential access
- ``self.log`` — instance-scoped logger
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hort.llming.powers import Power, PowerType
from hort.llming.pulse import PulseBus

if TYPE_CHECKING:
    from hort.ext.file_store import PluginFileStore
    from hort.ext.scheduler import PluginScheduler
    from hort.ext.store import PluginStore


class Llming:
    """Base class for all llmings. No mixins.

    Subclass this and override the methods you need. The framework
    handles lifecycle, service injection, and inter-llming routing.

    Example::

        class SystemMonitor(Llming):
            _latest: dict = {}

            def get_powers(self) -> list[Power]:
                return [
                    Power(
                        name="get_metrics",
                        type=PowerType.ACTION,
                        description="Get system metrics",
                        input_schema=MetricsRequest,
                        output_schema=MetricsResponse,
                    ),
                    Power(
                        name="cpu",
                        type=PowerType.COMMAND,
                        description="Show CPU usage",
                    ),
                ]

            async def execute_power(self, name: str, args: dict) -> Any:
                if name == "get_metrics":
                    return MetricsResponse(cpu=self._latest.get("cpu", 0))
                if name == "cpu":
                    return f"CPU: {self._latest.get('cpu', '?')}%"

            def get_pulse(self) -> dict:
                return self._latest
    """

    # ── Identity (set by the framework before activate) ──

    _instance_name: str = ""
    _class_name: str = ""

    # ── Soul (auto-loaded from SOUL.md by the framework) ──

    _soul_text: str = ""

    # ── Injected services ──

    _store: PluginStore | None = None        # legacy — use self.persist/self.runtime
    _files: PluginFileStore | None = None    # legacy — use self.persist.crates
    _storage: Any = None                     # Storage instance (runtime + persist)
    _scheduler: PluginScheduler | None = None
    _credentials: Any = None  # CredentialAccess
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

    def get_powers(self) -> list[Power]:
        """Declare all powers this llming provides.

        Return a list of Power objects. The framework routes MCP tool
        calls, slash commands, and action invocations to execute_power().
        """
        return []

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        """Execute a power by name.

        Called by the framework when an MCP tool, slash command, or action
        is invoked. The ``name`` matches ``Power.name``.

        For ACTION powers with Pydantic output_schema, return an instance
        of the output model. For COMMAND powers, return a string (text/HTML).
        For MCP powers, return a dict or MCP content blocks.
        """
        return {"error": f"Power {name} not implemented"}

    # ── Pulse ──

    def get_pulse(self) -> dict[str, Any]:
        """Return current live state (static read).

        Called by the framework for thumbnail rendering and by other
        llmings via ``read_pulse()``. Keep this lightweight.
        """
        return {}

    def get_pulse_channels(self) -> list[str]:
        """Declare subscribable event channels.

        Other llmings can subscribe to these via the message bus.
        """
        return []

    async def emit_pulse(self, event: str, data: dict[str, Any]) -> None:
        """Push an event to all subscribers of this instance."""
        if self._pulse_bus is not None:
            await self._pulse_bus.emit(self._instance_name, event, data)

    # ── Inter-llming communication (via message bus) ──

    async def call(self, target: str, power: str, args: dict[str, Any] | None = None) -> Any:
        """Call another llming's power. Goes through permission checks.

        This is the ONLY way to invoke another llming's functionality.
        Direct imports between llmings are forbidden.
        """
        from hort.llming.bus import MessageBus
        return await MessageBus.get().call(
            source=self._instance_name,
            target=target,
            power=power,
            args=args or {},
        )

    async def read_pulse(self, target: str) -> dict[str, Any]:
        """Read another llming's current pulse state."""
        if self._pulse_bus is not None:
            return self._pulse_bus.read_state(target)
        return {}

    def subscribe(self, target: str, event: str, handler: Any) -> None:
        """Subscribe to another llming's pulse events."""
        if self._pulse_bus is not None:
            self._pulse_bus.subscribe(target, event, handler)

    def unsubscribe(self, target: str, event: str) -> None:
        """Unsubscribe from pulse events."""
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
        """v1 compat: Return status for thumbnail rendering."""
        return self.get_pulse()

    def get_jobs(self) -> list[Any]:
        """v1 compat: Return scheduled job definitions.

        Override this if you need scheduled jobs. Jobs are declared
        in the manifest's ``jobs`` array, not in code.
        """
        return []
