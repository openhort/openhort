"""P2P plugin — WebRTC hole punching with relay signaling and Azure VM provisioning."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any

from hort.ext.connectors import (
    ConnectorCapabilities,
    ConnectorResponse,
    IncomingMessage,
)
from hort.llming import LlmingBase, Power, PowerType
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


class HolepunchPlugin(LlmingBase):
    """P2P hole punching with Azure VM provisioning for testing."""

    _stun_result: StunResult | None = None
    _punch_result: PunchResult | None = None
    _vm_status: Any = None
    _vm_manager: Any = None
    _stun_client: StunClient | None = None
    _relay_poller: Any = None
    _device_store: Any = None
    _room_id: str = ""
    _relay_url: str = "wss://relay.openhort.ai"
    _relay_http_url: str = "https://relay.openhort.ai"
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
        self._relay_http_url = config.get("relay_http_url", "https://relay.openhort.ai")

        # Device token store (MongoDB)
        from hort.peer2peer.device_tokens import DeviceTokenStore
        mongo_uri = config.get("mongodb_uri", "mongodb://localhost:27017")
        self._device_store = DeviceTokenStore(uri=mongo_uri)

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

        # Start relay poller (HTTP polling, no persistent WebSocket)
        self._start_relay_poller()

        # Azure VM manager
        self._vm_manager = AzureVMManager(
            resource_group=config.get("azure_resource_group", "openhort-peer2peer-rg"),
            region=config.get("azure_region", "westeurope"),
            vm_size=config.get("azure_vm_size", "Standard_B1ls"),
            vm_name=config.get("azure_vm_name", "openhort-punch-test"),
        )
        self.log.info("peer2peer plugin activated")

    def _start_relay_poller(self) -> None:
        """Start the relay poller in the background."""
        from hort.peer2peer.relay_poller import RelayPoller

        async def on_peer_connected(session_id: str, peer: Any) -> None:
            self.log.info("P2P peer connected via relay: %s", session_id)

        self._relay_poller = RelayPoller(
            relay_url=self._relay_url,
            relay_http_url=self._relay_http_url,
            room_id=self._room_id,
            device_store=self._device_store,
            on_peer_connected=on_peer_connected,
        )

        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._relay_poller.start())
            self.log.info("relay poller starting on room %s", self._room_id)
        except RuntimeError:
            self.log.warning("no event loop — relay poller not started")

    def deactivate(self) -> None:
        if self._relay_poller:
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self._relay_poller.stop())
            except RuntimeError:
                pass
        self.log.info("peer2peer plugin deactivated")

    def get_pulse(self) -> dict[str, Any]:
        """Return status for thumbnail/dashboard rendering."""
        paired_count = len(self._device_store.list_devices()) if self._device_store else 0
        return {
            "stun": {
                "public_ip": self._stun_result.public_ip if self._stun_result else None,
                "public_port": self._stun_result.public_port if self._stun_result else None,
                "nat_type": self._stun_result.nat_type.value if self._stun_result else None,
            },
            "relay": {
                "mode": "polling",
                "running": self._relay_poller.is_running if self._relay_poller else False,
                "active_sessions": self._relay_poller.active_sessions if self._relay_poller else 0,
                "paired_devices": paired_count,
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

    # ===== Powers =====

    def get_powers(self) -> list[Power]:
        return [
            # MCP tools
            Power(
                name="peer2peer_stun_discover",
                type=PowerType.MCP,
                description="Discover public IP:port via STUN and detect NAT type",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="peer2peer_vm_create",
                type=PowerType.MCP,
                description="Create a minimal Azure VM for hole punch testing (auto-shuts down at midnight)",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="peer2peer_vm_status",
                type=PowerType.MCP,
                description="Get current Azure VM status",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="peer2peer_vm_start",
                type=PowerType.MCP,
                description="Start the Azure VM if deallocated",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="peer2peer_vm_stop",
                type=PowerType.MCP,
                description="Deallocate the Azure VM (stops billing)",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="peer2peer_vm_destroy",
                type=PowerType.MCP,
                description="Delete the Azure VM and all resources",
                input_schema={"type": "object", "properties": {}},
            ),
            # Slash commands
            Power(
                name="pair",
                type=PowerType.COMMAND,
                description="Pair a mobile device (one-time setup)",
            ),
            Power(
                name="devices",
                type=PowerType.COMMAND,
                description="List or revoke paired devices",
            ),
            Power(
                name="connect",
                type=PowerType.COMMAND,
                description="Connect via Telegram",
            ),
            Power(
                name="p2p",
                type=PowerType.COMMAND,
                description="Get a direct P2P link for any browser",
            ),
            Power(
                name="stun",
                type=PowerType.COMMAND,
                description="Discover public IP and NAT type via STUN",
            ),
            Power(
                name="vm",
                type=PowerType.COMMAND,
                description="Manage Azure test VM (create/status/start/stop/destroy)",
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        # MCP tools
        if name == "peer2peer_stun_discover":
            return await self._mcp_stun_discover()
        if name == "peer2peer_vm_create":
            return await self._mcp_vm_create()
        if name == "peer2peer_vm_status":
            return await self._mcp_vm_status()
        if name == "peer2peer_vm_start":
            return await self._mcp_vm_start()
        if name == "peer2peer_vm_stop":
            return await self._mcp_vm_stop()
        if name == "peer2peer_vm_destroy":
            return await self._mcp_vm_destroy()

        # Slash commands
        message = args.get("_message")
        if name == "pair" and message:
            return await self._cmd_pair(message)
        if name == "devices":
            cmd_args = args.get("args", "")
            return await self._cmd_devices(cmd_args)
        if name == "connect" and message:
            return await self._cmd_connect(message)
        if name == "p2p" and message:
            return await self._cmd_p2p(message)
        if name == "stun":
            return await self._cmd_stun()
        if name == "vm":
            cmd_args = args.get("args", "")
            return await self._cmd_vm(cmd_args)

        return {"error": f"Unknown power: {name}"}

    async def _mcp_stun_discover(self) -> dict[str, Any]:
        if not self._stun_client:
            return {
                "content": [{"type": "text", "text": "Plugin not activated"}],
                "is_error": True,
            }
        try:
            self._stun_result = await self._stun_client.detect_nat_type()
            return {"content": [{"type": "text", "text": (
                f"Public: {self._stun_result.public_ip}:{self._stun_result.public_port}\n"
                f"Local: {self._stun_result.local_ip}:{self._stun_result.local_port}\n"
                f"NAT type: {self._stun_result.nat_type.value}\n"
                f"Punchable: {self._stun_result.nat_type.punchable}"
            )}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"STUN failed: {exc}"}],
                "is_error": True,
            }

    async def _mcp_vm_create(self) -> dict[str, Any]:
        if not self._vm_manager:
            return {
                "content": [{"type": "text", "text": "Plugin not activated"}],
                "is_error": True,
            }
        try:
            self._vm_status = await self._vm_manager.create_vm()
            return {"content": [{"type": "text", "text": (
                f"VM created: {self._vm_status.name}\n"
                f"IP: {self._vm_status.public_ip}\n"
                f"State: {self._vm_status.power_state}\n"
                f"Auto-shutdown: midnight UTC\n"
                f"Signal relay: ws://{self._vm_status.public_ip}:9100"
            )}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"VM creation failed: {exc}"}],
                "is_error": True,
            }

    async def _mcp_vm_status(self) -> dict[str, Any]:
        if not self._vm_manager:
            return {
                "content": [{"type": "text", "text": "Plugin not activated"}],
                "is_error": True,
            }
        self._vm_status = await self._vm_manager.get_status()
        if not self._vm_status.exists:
            return {"content": [{"type": "text", "text": "VM does not exist"}]}
        return {"content": [{"type": "text", "text": (
            f"VM: {self._vm_status.name}\n"
            f"State: {self._vm_status.power_state}\n"
            f"IP: {self._vm_status.public_ip}"
        )}]}

    async def _mcp_vm_start(self) -> dict[str, Any]:
        if not self._vm_manager:
            return {
                "content": [{"type": "text", "text": "Plugin not activated"}],
                "is_error": True,
            }
        self._vm_status = await self._vm_manager.start_vm()
        return {"content": [{"type": "text", "text": f"VM started: {self._vm_status.power_state}"}]}

    async def _mcp_vm_stop(self) -> dict[str, Any]:
        if not self._vm_manager:
            return {
                "content": [{"type": "text", "text": "Plugin not activated"}],
                "is_error": True,
            }
        self._vm_status = await self._vm_manager.stop_vm()
        return {"content": [{"type": "text", "text": f"VM deallocated: {self._vm_status.power_state}"}]}

    async def _mcp_vm_destroy(self) -> dict[str, Any]:
        if not self._vm_manager:
            return {
                "content": [{"type": "text", "text": "Plugin not activated"}],
                "is_error": True,
            }
        ok = await self._vm_manager.destroy_vm()
        self._vm_status = VMStatus(exists=False)
        return {"content": [{"type": "text", "text": "VM destroyed" if ok else "VM destroy failed"}]}

    # ===== Compat: pass full message/capabilities to execute_power =====

    async def handle_connector_command(
        self,
        command: str,
        message: IncomingMessage,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorResponse | None:
        """Override compat bridge to pass message and capabilities."""
        cmd_args = getattr(message, "command_args", "") or ""
        result = await self.execute_power(command, {
            "args": cmd_args,
            "_message": message,
            "_capabilities": capabilities,
        })
        if result is None:
            return None
        if isinstance(result, ConnectorResponse):
            return result
        if isinstance(result, str):
            return ConnectorResponse.simple(result)
        return result

    async def _cmd_pair(self, message: IncomingMessage) -> ConnectorResponse:
        """Pair a mobile device — generates a deep link with a permanent device token."""
        if not self._device_store:
            return ConnectorResponse.simple("Device store not available")

        label = message.command_args.strip() if message.command_args else (
            f"{message.username}'s device" if message.username else "Device"
        )

        # Generate permanent device token (256-bit, shown once)
        from urllib.parse import quote
        token = self._device_store.create(label=label)
        deep_link = (
            f"openhort://pair?token={quote(token, safe='')}"
            f"&room={quote(self._room_id, safe='')}"
            f"&relay={quote(self._relay_url, safe='')}"
        )

        self.log.info("generated pairing token for %s", label)

        # Start fast polling to detect when the device first connects
        if self._relay_poller:
            self._relay_poller.start_pairing_poll()

        # Generate QR code
        try:
            from hort.network import generate_qr_data_uri
            qr = generate_qr_data_uri(deep_link)
            qr_html = f'<img src="{qr}" width="200" />'
        except Exception:
            qr_html = ""

        return ConnectorResponse(
            text=(
                f"Pair your device:\n{deep_link}\n\n"
                f"Open this link on your phone, or scan the QR code.\n"
                f"Device: {label}"
            ),
            html=(
                f"{qr_html}\n"
                f'<a href="{deep_link}">Tap to pair: {label}</a>\n'
                f"<i>Open in the OpenHort app on your phone.</i>"
            ),
        )

    async def _cmd_devices(self, args: str) -> ConnectorResponse:
        """List or revoke paired devices."""
        if not self._device_store:
            return ConnectorResponse.simple("Device store not available")

        subcmd = args.strip().lower() if args else ""

        if subcmd.startswith("revoke "):
            hash_prefix = subcmd[7:].strip()
            if not hash_prefix:
                return ConnectorResponse.simple("Usage: /devices revoke <hash_prefix>")
            devices = self._device_store.list_devices()
            for d in devices:
                if d["token_hash"].startswith(hash_prefix):
                    self._device_store.revoke(d["token_hash"])
                    return ConnectorResponse.simple(f"Revoked: {d['label']} ({d['token_hash'][:12]}...)")
            return ConnectorResponse.simple(f"No device found matching: {hash_prefix}")

        if subcmd == "revoke-all":
            count = self._device_store.revoke_all()
            return ConnectorResponse.simple(f"Revoked {count} device(s)")

        # List devices
        devices = self._device_store.list_devices()
        if not devices:
            return ConnectorResponse.simple("No paired devices. Use /pair to add one.")

        lines = [f"<b>Paired devices ({len(devices)}):</b>"]
        for d in devices:
            seen = d.get("last_seen") or "never"
            lines.append(
                f"  {d['label']} — <code>{d['token_hash'][:12]}...</code> — last seen: {seen}"
            )
        lines.append("\nUse /devices revoke <hash_prefix> to remove a device.")

        return ConnectorResponse(
            text="\n".join(lines).replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""),
            html="\n".join(lines),
        )

    async def _cmd_connect(self, message: IncomingMessage) -> ConnectorResponse:
        """Generate a one-time P2P connection link with auth token."""
        if not self._relay_poller:
            return ConnectorResponse.simple("P2P relay not running")

        token = self._relay_poller.tokens.generate()
        viewer_base = "https://openhort.ai/p2p/viewer.html"
        url = f"{viewer_base}?signal=ws&room={self._room_id}&token={token}"

        self.log.info("generated connection token for user %s", message.username or message.user_id)

        return ConnectorResponse(
            text=f"Tap to connect (expires in 60s):\n{url}",
            html=f'<a href="{url}">Open openhort</a>\n<i>Link expires in 60 seconds.</i>',
        )

    async def _cmd_p2p(self, message: IncomingMessage) -> ConnectorResponse:
        """Generate a plain URL for opening in any browser."""
        if not self._relay_poller:
            return ConnectorResponse.simple("P2P relay not running")

        token = self._relay_poller.tokens.generate()
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
