"""P2P plugin — WebRTC hole punching with relay signaling and Azure VM provisioning."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any

from hort.ext.connectors import (
    ConnectorCapabilities,
    ConnectorCommand,
    ConnectorMixin,
    ConnectorResponse,
    IncomingMessage,
)
from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin
from hort.peer2peer import HolePuncher, StunClient
from hort.peer2peer.models import NatType, PunchResult, StunResult

logger = logging.getLogger(__name__)


def _load_azure_vm():  # type: ignore[no-untyped-def]
    """Lazy import of azure_vm module (avoids relative import issues in plugin loader)."""
    import importlib.util
    import sys
    from pathlib import Path

    mod_name = "hort.extensions.core.peer2peer.azure_vm"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
        return mod.AzureVMManager, mod.VMStatus

    module_file = Path(__file__).parent / "azure_vm.py"
    spec = importlib.util.spec_from_file_location(mod_name, module_file)
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod.AzureVMManager, mod.VMStatus
    msg = "Failed to load azure_vm module"
    raise ImportError(msg)


# Lazy-loaded at activate time
AzureVMManager = None  # type: ignore[assignment]
VMStatus = None  # type: ignore[assignment]


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine from sync context (executor thread)."""
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


class HolepunchPlugin(PluginBase, ScheduledMixin, MCPMixin, ConnectorMixin):
    """P2P hole punching with Azure VM provisioning for testing."""

    _stun_result: StunResult | None = None
    _punch_result: PunchResult | None = None
    _vm_status: Any = None
    _vm_manager: Any = None
    _stun_client: StunClient | None = None
    _relay_listener: Any = None
    _room_id: str = ""
    _relay_url: str = "wss://relay.openhort.ai"
    _VMStatus: Any = None  # lazy-loaded class ref

    def activate(self, config: dict[str, Any]) -> None:
        global AzureVMManager, VMStatus  # noqa: PLW0603
        AzureVMManager, VMStatus = _load_azure_vm()
        self._VMStatus = VMStatus
        self._vm_status = VMStatus(exists=False)

        # Room ID: full SHA-256 of bot token (32 hex chars = 128 bits)
        # Combined with one-time token (256 bits), total entropy is 384 bits
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if bot_token:
            self._room_id = hashlib.sha256(bot_token.encode()).hexdigest()
        else:
            self._room_id = hashlib.sha256(os.urandom(32)).hexdigest()

        self._relay_url = config.get("relay_url", "wss://relay.openhort.ai")

        # Parse STUN servers from config
        stun_servers_raw = config.get("stun_servers", ["stun.l.google.com:19302"])
        stun_servers = []
        for s in stun_servers_raw:
            if ":" in s:
                host, port = s.rsplit(":", 1)
                stun_servers.append((host, int(port)))
            else:
                stun_servers.append((s, 3478))
        self._stun_client = StunClient(stun_servers=stun_servers)

        # Start relay listener (connects to relay, waits for SDP offers)
        self._start_relay_listener()

        # Azure VM manager
        self._vm_manager = AzureVMManager(
            resource_group=config.get("azure_resource_group", "openhort-peer2peer-rg"),
            region=config.get("azure_region", "westeurope"),
            vm_size=config.get("azure_vm_size", "Standard_B1ls"),
            vm_name=config.get("azure_vm_name", "openhort-punch-test"),
        )
        self.log.info("peer2peer plugin activated")

    def _start_relay_listener(self) -> None:
        """Start the relay listener in the background."""
        from hort.peer2peer.relay_listener import RelayListener

        async def on_peer_connected(session_id: str, peer: Any) -> None:
            self.log.info("P2P peer connected via relay: %s", session_id)

        async def on_message(data: bytes | str) -> None:
            self.log.debug("P2P message from relay peer: %d bytes", len(data) if isinstance(data, bytes) else len(str(data)))

        self._relay_listener = RelayListener(
            relay_url=self._relay_url,
            room_id=self._room_id,
            on_peer_connected=on_peer_connected,
            on_message=on_message,
        )

        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._relay_listener.start())
            self.log.info("relay listener starting on room %s", self._room_id)
        except RuntimeError:
            self.log.warning("no event loop — relay listener not started")

    def deactivate(self) -> None:
        if self._relay_listener:
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self._relay_listener.stop())
            except RuntimeError:
                pass
        self.log.info("peer2peer plugin deactivated")

    def get_status(self) -> dict[str, Any]:
        """Return status for thumbnail/dashboard rendering."""
        return {
            "stun": {
                "public_ip": self._stun_result.public_ip if self._stun_result else None,
                "public_port": self._stun_result.public_port if self._stun_result else None,
                "nat_type": self._stun_result.nat_type.value if self._stun_result else None,
            },
            "punch": {
                "success": self._punch_result.success if self._punch_result else None,
                "remote_addr": (
                    f"{self._punch_result.remote_addr[0]}:{self._punch_result.remote_addr[1]}"
                    if self._punch_result and self._punch_result.success
                    else None
                ),
                "rtt_ms": self._punch_result.rtt_ms if self._punch_result else None,
            },
            "vm": {
                "exists": self._vm_status.exists,
                "power_state": self._vm_status.power_state,
                "public_ip": self._vm_status.public_ip,
            },
        }

    # ===== Scheduler =====

    def check_vm_status(self) -> None:
        """Poll Azure VM status. Runs in executor thread."""
        if not self._vm_manager:
            return
        try:
            self._vm_status = _run_coro(self._vm_manager.get_status())
        except Exception as exc:
            self.log.debug("VM status check failed: %s", exc)

    # ===== MCP Tools =====

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="peer2peer_stun_discover",
                description="Discover public IP:port via STUN and detect NAT type",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="peer2peer_vm_create",
                description="Create a minimal Azure VM for hole punch testing (auto-shuts down at midnight)",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="peer2peer_vm_status",
                description="Get current Azure VM status",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="peer2peer_vm_start",
                description="Start the Azure VM if deallocated",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="peer2peer_vm_stop",
                description="Deallocate the Azure VM (stops billing)",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="peer2peer_vm_destroy",
                description="Delete the Azure VM and all resources",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        if tool_name == "peer2peer_stun_discover":
            return await self._mcp_stun_discover()
        if tool_name == "peer2peer_vm_create":
            return await self._mcp_vm_create()
        if tool_name == "peer2peer_vm_status":
            return await self._mcp_vm_status()
        if tool_name == "peer2peer_vm_start":
            return await self._mcp_vm_start()
        if tool_name == "peer2peer_vm_stop":
            return await self._mcp_vm_stop()
        if tool_name == "peer2peer_vm_destroy":
            return await self._mcp_vm_destroy()
        return MCPToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            is_error=True,
        )

    async def _mcp_stun_discover(self) -> MCPToolResult:
        if not self._stun_client:
            return MCPToolResult(
                content=[{"type": "text", "text": "Plugin not activated"}],
                is_error=True,
            )
        try:
            self._stun_result = await self._stun_client.detect_nat_type()
            return MCPToolResult(content=[{"type": "text", "text": (
                f"Public: {self._stun_result.public_ip}:{self._stun_result.public_port}\n"
                f"Local: {self._stun_result.local_ip}:{self._stun_result.local_port}\n"
                f"NAT type: {self._stun_result.nat_type.value}\n"
                f"Punchable: {self._stun_result.nat_type.punchable}"
            )}])
        except Exception as exc:
            return MCPToolResult(
                content=[{"type": "text", "text": f"STUN failed: {exc}"}],
                is_error=True,
            )

    async def _mcp_vm_create(self) -> MCPToolResult:
        if not self._vm_manager:
            return MCPToolResult(
                content=[{"type": "text", "text": "Plugin not activated"}],
                is_error=True,
            )
        try:
            self._vm_status = await self._vm_manager.create_vm()
            return MCPToolResult(content=[{"type": "text", "text": (
                f"VM created: {self._vm_status.name}\n"
                f"IP: {self._vm_status.public_ip}\n"
                f"State: {self._vm_status.power_state}\n"
                f"Auto-shutdown: midnight UTC\n"
                f"Signal relay: ws://{self._vm_status.public_ip}:9100"
            )}])
        except Exception as exc:
            return MCPToolResult(
                content=[{"type": "text", "text": f"VM creation failed: {exc}"}],
                is_error=True,
            )

    async def _mcp_vm_status(self) -> MCPToolResult:
        if not self._vm_manager:
            return MCPToolResult(
                content=[{"type": "text", "text": "Plugin not activated"}],
                is_error=True,
            )
        self._vm_status = await self._vm_manager.get_status()
        if not self._vm_status.exists:
            return MCPToolResult(content=[{"type": "text", "text": "VM does not exist"}])
        return MCPToolResult(content=[{"type": "text", "text": (
            f"VM: {self._vm_status.name}\n"
            f"State: {self._vm_status.power_state}\n"
            f"IP: {self._vm_status.public_ip}"
        )}])

    async def _mcp_vm_start(self) -> MCPToolResult:
        if not self._vm_manager:
            return MCPToolResult(
                content=[{"type": "text", "text": "Plugin not activated"}],
                is_error=True,
            )
        self._vm_status = await self._vm_manager.start_vm()
        return MCPToolResult(content=[{"type": "text", "text": f"VM started: {self._vm_status.power_state}"}])

    async def _mcp_vm_stop(self) -> MCPToolResult:
        if not self._vm_manager:
            return MCPToolResult(
                content=[{"type": "text", "text": "Plugin not activated"}],
                is_error=True,
            )
        self._vm_status = await self._vm_manager.stop_vm()
        return MCPToolResult(content=[{"type": "text", "text": f"VM deallocated: {self._vm_status.power_state}"}])

    async def _mcp_vm_destroy(self) -> MCPToolResult:
        if not self._vm_manager:
            return MCPToolResult(
                content=[{"type": "text", "text": "Plugin not activated"}],
                is_error=True,
            )
        ok = await self._vm_manager.destroy_vm()
        self._vm_status = VMStatus(exists=False)
        return MCPToolResult(content=[{"type": "text", "text": "VM destroyed" if ok else "VM destroy failed"}])

    # ===== Connector Commands =====

    def get_connector_commands(self) -> list[ConnectorCommand]:
        return [
            ConnectorCommand(
                name="connect",
                description="Connect via Telegram",
                plugin_id="peer2peer",
            ),
            ConnectorCommand(
                name="p2p",
                description="Get a direct P2P link for any browser",
                plugin_id="peer2peer",
            ),
            ConnectorCommand(
                name="stun",
                description="Discover public IP and NAT type via STUN",
                plugin_id="peer2peer",
            ),
            ConnectorCommand(
                name="vm",
                description="Manage Azure test VM (create/status/start/stop/destroy)",
                plugin_id="peer2peer",
                usage="/vm <create|status|start|stop|destroy>",
            ),
        ]

    async def handle_connector_command(
        self,
        command: str,
        message: IncomingMessage,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorResponse | None:
        if command == "connect":
            return await self._cmd_connect(message)
        if command == "p2p":
            return await self._cmd_p2p(message)
        if command == "stun":
            return await self._cmd_stun()
        if command == "vm":
            return await self._cmd_vm(message.command_args)
        return None

    async def _cmd_connect(self, message: IncomingMessage) -> ConnectorResponse:
        """Generate a one-time P2P connection link with auth token."""
        if not self._relay_listener:
            return ConnectorResponse.simple("P2P relay not connected")

        token = self._relay_listener.tokens.generate()
        viewer_base = "https://openhort.ai/p2p/viewer.html"  # TODO: make configurable
        url = f"{viewer_base}?signal=ws&room={self._room_id}&token={token}"

        self.log.info("generated connection token for user %s", message.username or message.user_id)

        return ConnectorResponse(
            text=f"Tap to connect (expires in 60s):\n{url}",
            html=f'<a href="{url}">Open openhort</a>\n<i>Link expires in 60 seconds.</i>',
        )

    async def _cmd_p2p(self, message: IncomingMessage) -> ConnectorResponse:
        """Generate a plain URL for opening in any browser."""
        if not self._relay_listener:
            return ConnectorResponse.simple("P2P relay not connected")

        token = self._relay_listener.tokens.generate()
        viewer_base = "https://openhort.ai/p2p/viewer.html"
        url = f"{viewer_base}?signal=ws&room={self._room_id}&token={token}"

        self.log.info("generated browser link for user %s", message.username or message.user_id)

        return ConnectorResponse.simple(f"{url}\n\nOpen in any browser. Expires in 60s.")

    async def _cmd_stun(self) -> ConnectorResponse:
        if not self._stun_client:
            return ConnectorResponse.simple("Plugin not activated")
        try:
            self._stun_result = await self._stun_client.detect_nat_type()
            r = self._stun_result
            punchable = "yes" if r.nat_type.punchable else "NO"
            return ConnectorResponse(
                text=(
                    f"Public: {r.public_ip}:{r.public_port}\n"
                    f"NAT: {r.nat_type.value}\n"
                    f"Punchable: {punchable}"
                ),
                html=(
                    f"<b>Public:</b> {r.public_ip}:{r.public_port}\n"
                    f"<b>NAT:</b> {r.nat_type.value}\n"
                    f"<b>Punchable:</b> {punchable}"
                ),
            )
        except Exception as exc:
            return ConnectorResponse.simple(f"STUN failed: {exc}")

    async def _cmd_vm(self, args: str) -> ConnectorResponse:
        if not self._vm_manager:
            return ConnectorResponse.simple("Plugin not activated")

        subcmd = args.strip().lower() if args else "status"

        if subcmd == "create":
            auth_ok = await self._vm_manager.check_az_auth()
            if not auth_ok:
                return ConnectorResponse.simple(
                    "Azure CLI not authenticated. Run: az login"
                )
            try:
                self._vm_status = await self._vm_manager.create_vm()
                return ConnectorResponse(
                    text=(
                        f"VM created: {self._vm_status.name}\n"
                        f"IP: {self._vm_status.public_ip}\n"
                        f"Auto-shutdown: midnight UTC"
                    ),
                    html=(
                        f"<b>VM created:</b> {self._vm_status.name}\n"
                        f"<b>IP:</b> <code>{self._vm_status.public_ip}</code>\n"
                        f"<b>Auto-shutdown:</b> midnight UTC"
                    ),
                )
            except Exception as exc:
                return ConnectorResponse.simple(f"Failed: {exc}")

        if subcmd == "start":
            self._vm_status = await self._vm_manager.start_vm()
            return ConnectorResponse.simple(f"VM started: {self._vm_status.power_state}")

        if subcmd == "stop":
            self._vm_status = await self._vm_manager.stop_vm()
            return ConnectorResponse.simple(f"VM deallocated: {self._vm_status.power_state}")

        if subcmd == "destroy":
            ok = await self._vm_manager.destroy_vm()
            self._vm_status = VMStatus(exists=False)
            return ConnectorResponse.simple("VM destroyed" if ok else "Destroy failed")

        # Default: status
        self._vm_status = await self._vm_manager.get_status()
        if not self._vm_status.exists:
            return ConnectorResponse.simple("No VM exists. Use /vm create")
        return ConnectorResponse(
            text=(
                f"VM: {self._vm_status.name}\n"
                f"State: {self._vm_status.power_state}\n"
                f"IP: {self._vm_status.public_ip}"
            ),
            html=(
                f"<b>VM:</b> {self._vm_status.name}\n"
                f"<b>State:</b> {self._vm_status.power_state}\n"
                f"<b>IP:</b> <code>{self._vm_status.public_ip}</code>"
            ),
        )
