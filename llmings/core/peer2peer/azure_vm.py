"""Azure VM provisioning for hole punch testing.

Creates a minimal B1ls Ubuntu VM with auto-shutdown at midnight.
Uses `az` CLI (consistent with existing openhort deployment tooling).
All subprocess calls are async to never block the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VMStatus:
    """Current state of the Azure VM."""

    exists: bool
    power_state: str = ""  # "running", "deallocated", "stopped", ""
    public_ip: str = ""
    name: str = ""
    resource_group: str = ""
    region: str = ""
    vm_size: str = ""


# Cloud-init script: minimal Python signaling relay
_CLOUD_INIT = """\
#!/bin/bash
set -e
apt-get update -qq && apt-get install -y -qq python3-websockets > /dev/null

cat > /opt/signal_relay.py << 'PYEOF'
import asyncio, websockets
rooms: dict[str, list] = {}

async def handler(ws, path=""):
    room = path.strip("/") or "default"
    if room not in rooms:
        rooms[room] = []
    peers = rooms[room]
    peers.append(ws)
    try:
        async for msg in ws:
            for peer in list(peers):
                if peer != ws:
                    try:
                        await peer.send(msg)
                    except Exception:
                        pass
    finally:
        peers.remove(ws)
        if not peers:
            rooms.pop(room, None)

async def main():
    async with websockets.serve(handler, "0.0.0.0", 9100):
        await asyncio.Future()

asyncio.run(main())
PYEOF

cat > /etc/systemd/system/signal-relay.service << 'SVCEOF'
[Unit]
Description=Hole Punch Signal Relay
After=network.target
[Service]
ExecStart=/usr/bin/python3 /opt/signal_relay.py
Restart=always
[Install]
WantedBy=multi-user.target
SVCEOF

systemctl enable signal-relay && systemctl start signal-relay
"""


async def _run_az(*args: str) -> tuple[int, str, str]:
    """Run an az CLI command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        "az", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode().strip(),
        stderr.decode().strip(),
    )


class AzureVMManager:
    """Provisions and manages a minimal Azure VM for hole punch relay testing."""

    def __init__(
        self,
        resource_group: str = "openhort-peer2peer-rg",
        region: str = "westeurope",
        vm_size: str = "Standard_B1ls",
        vm_name: str = "openhort-punch-test",
    ) -> None:
        self.rg = resource_group
        self.region = region
        self.vm_size = vm_size
        self.vm_name = vm_name

    async def ensure_resource_group(self) -> None:
        """Create the resource group if it doesn't exist."""
        rc, _, _ = await _run_az(
            "group", "show", "--name", self.rg, "--output", "none"
        )
        if rc != 0:
            await _run_az(
                "group", "create",
                "--name", self.rg,
                "--location", self.region,
                "--output", "none",
            )

    async def create_vm(self) -> VMStatus:
        """Create a minimal VM with signaling relay and auto-shutdown.

        Returns the VM status after creation.
        """
        await self.ensure_resource_group()

        logger.info("creating VM %s in %s (%s)", self.vm_name, self.rg, self.vm_size)

        rc, out, err = await _run_az(
            "vm", "create",
            "--resource-group", self.rg,
            "--name", self.vm_name,
            "--image", "Canonical:ubuntu-24_04-lts:server:latest",
            "--size", self.vm_size,
            "--admin-username", "openhort",
            "--generate-ssh-keys",
            "--public-ip-sku", "Basic",
            "--custom-data", _CLOUD_INIT,
            "--output", "json",
        )
        if rc != 0:
            msg = f"VM creation failed: {err}"
            raise RuntimeError(msg)

        # Open UDP port range + signaling WS port
        await _run_az(
            "vm", "open-port",
            "--resource-group", self.rg,
            "--name", self.vm_name,
            "--port", "9100",
            "--priority", "1010",
            "--output", "none",
        )
        await _run_az(
            "network", "nsg", "rule", "create",
            "--resource-group", self.rg,
            "--nsg-name", f"{self.vm_name}NSG",
            "--name", "AllowUDP",
            "--priority", "1020",
            "--protocol", "Udp",
            "--destination-port-ranges", "10000-20000",
            "--access", "Allow",
            "--output", "none",
        )

        # Auto-shutdown at midnight UTC
        await _run_az(
            "vm", "auto-shutdown",
            "--resource-group", self.rg,
            "--name", self.vm_name,
            "--time", "0000",
            "--output", "none",
        )

        return await self.get_status()

    async def get_status(self) -> VMStatus:
        """Get current VM status."""
        rc, out, _ = await _run_az(
            "vm", "show",
            "--resource-group", self.rg,
            "--name", self.vm_name,
            "--show-details",
            "--output", "json",
        )
        if rc != 0:
            return VMStatus(exists=False, name=self.vm_name, resource_group=self.rg)

        try:
            info = json.loads(out)
        except json.JSONDecodeError:
            return VMStatus(exists=False, name=self.vm_name, resource_group=self.rg)

        return VMStatus(
            exists=True,
            power_state=info.get("powerState", "").replace("VM ", "").lower(),
            public_ip=info.get("publicIps", ""),
            name=self.vm_name,
            resource_group=self.rg,
            region=self.region,
            vm_size=self.vm_size,
        )

    async def start_vm(self) -> VMStatus:
        """Start the VM if it's deallocated."""
        await _run_az(
            "vm", "start",
            "--resource-group", self.rg,
            "--name", self.vm_name,
            "--output", "none",
        )
        return await self.get_status()

    async def stop_vm(self) -> VMStatus:
        """Deallocate the VM (stops billing)."""
        await _run_az(
            "vm", "deallocate",
            "--resource-group", self.rg,
            "--name", self.vm_name,
            "--output", "none",
        )
        return await self.get_status()

    async def destroy_vm(self) -> bool:
        """Delete the VM and all associated resources."""
        logger.info("destroying VM %s in %s", self.vm_name, self.rg)
        rc, _, err = await _run_az(
            "group", "delete",
            "--name", self.rg,
            "--yes",
            "--no-wait",
            "--output", "none",
        )
        return rc == 0

    async def check_az_auth(self) -> bool:
        """Check if az CLI is authenticated."""
        rc, _, _ = await _run_az("account", "show", "--output", "none")
        return rc == 0
