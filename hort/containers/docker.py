"""Docker container provider — manages containers via the Docker CLI."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from hort.containers.base import (
    ContainerConfig,
    ContainerInfo,
    ContainerProvider,
    ExecResult,
)

# IsoClaude-compatible port offset: container 8xxx → host 9xxx
DEFAULT_PORT_OFFSET = 1000


class DockerProvider(ContainerProvider):
    """Local Docker container management via CLI.

    Uses ``docker`` commands (no Docker SDK dependency) for maximum
    compatibility with IsoClaude and minimal dependencies.
    """

    def __init__(self, port_offset: int = DEFAULT_PORT_OFFSET) -> None:
        self._port_offset = port_offset

    @property
    def provider_name(self) -> str:
        return "docker"

    async def create(self, config: ContainerConfig) -> ContainerInfo:
        """Create a container (docker create)."""
        cmd = ["docker", "create", "--name", config.name]

        # Port mapping
        mapped_ports: dict[int, int] = {}
        for container_port, host_port in config.ports.items():
            if host_port == 0:
                host_port = container_port + self._port_offset
            mapped_ports[container_port] = host_port
            cmd.extend(["-p", f"{host_port}:{container_port}"])

        # Environment
        for key, val in config.env.items():
            cmd.extend(["-e", f"{key}={val}"])

        # Mounts
        for mount in config.mounts:
            flag = f"{mount.host_path}:{mount.container_path}"
            if mount.read_only:
                flag += ":ro"
            cmd.extend(["-v", flag])

        # Working directory
        cmd.extend(["-w", config.working_dir])

        # Resource limits
        cmd.extend(["--memory", f"{config.memory_mb}m"])
        cmd.extend(["--cpus", str(config.cpu_count)])

        # Image and optional command
        cmd.append(config.image)
        if config.command:
            cmd.extend(["sh", "-c", config.command])

        result = await _run(cmd)
        container_id = result.stdout.strip()[:12]

        return ContainerInfo(
            container_id=container_id,
            name=config.name,
            status="created",
            image=config.image,
            ports=mapped_ports,
            provider="docker",
        )

    async def start(self, container_id: str) -> bool:
        result = await _run(["docker", "start", container_id])
        return result.exit_code == 0

    async def stop(self, container_id: str) -> bool:
        result = await _run(["docker", "stop", container_id])
        return result.exit_code == 0

    async def destroy(self, container_id: str) -> bool:
        await _run(["docker", "stop", container_id])
        result = await _run(["docker", "rm", "-v", container_id])
        return result.exit_code == 0

    async def exec(
        self, container_id: str, command: str, timeout: float = 30.0
    ) -> ExecResult:
        return await _run(
            ["docker", "exec", container_id, "sh", "-c", command],
            timeout=timeout,
        )

    async def get_info(self, container_id: str) -> ContainerInfo | None:
        result = await _run([
            "docker", "inspect", "--format",
            '{{json .}}',
            container_id,
        ])
        if result.exit_code != 0:
            return None
        try:
            data: dict[str, Any] = json.loads(result.stdout)
            state = data.get("State", {})
            status = "running" if state.get("Running") else "stopped"
            name = data.get("Name", "").lstrip("/")
            image = data.get("Config", {}).get("Image", "")

            # Parse port bindings
            ports: dict[int, int] = {}
            bindings = (
                data.get("HostConfig", {}).get("PortBindings") or {}
            )
            for container_port_str, host_bindings in bindings.items():
                cp = int(container_port_str.split("/")[0])
                if host_bindings:
                    hp = int(host_bindings[0].get("HostPort", 0))
                    if hp:
                        ports[cp] = hp

            return ContainerInfo(
                container_id=container_id,
                name=name,
                status=status,
                image=image,
                ports=ports,
                provider="docker",
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    async def list_containers(self) -> list[ContainerInfo]:
        result = await _run([
            "docker", "ps", "-a", "--format",
            '{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}',
        ])
        if result.exit_code != 0:
            return []
        containers: list[ContainerInfo] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            cid, name, status_str, image = parts[0], parts[1], parts[2], parts[3]
            status = "running" if "Up" in status_str else "stopped"
            containers.append(ContainerInfo(
                container_id=cid,
                name=name,
                status=status,
                image=image,
                provider="docker",
            ))
        return containers

    async def get_url(
        self, container_id: str, container_port: int
    ) -> str | None:
        info = await self.get_info(container_id)
        if info is None:
            return None
        host_port = info.ports.get(container_port)
        if host_port:
            return f"http://localhost:{host_port}"
        return None


async def _run(
    cmd: list[str], timeout: float = 30.0
) -> ExecResult:
    """Run a command and return the result."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return ExecResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )
    except asyncio.TimeoutError:
        return ExecResult(exit_code=-1, stdout="", stderr="Command timed out")
    except FileNotFoundError:
        return ExecResult(
            exit_code=-1, stdout="", stderr="docker not found in PATH"
        )
