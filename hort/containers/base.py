"""Abstract base types for container management."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MountConfig:
    """A volume or bind mount."""

    host_path: str
    container_path: str
    read_only: bool = False


@dataclass(frozen=True)
class ContainerConfig:
    """Configuration for creating a container."""

    name: str
    image: str
    command: str | None = None
    ports: dict[int, int] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    mounts: list[MountConfig] = field(default_factory=list)
    working_dir: str = "/app"
    memory_mb: int = 512
    cpu_count: float = 1.0


@dataclass(frozen=True)
class ContainerInfo:
    """Runtime state of a container."""

    container_id: str
    name: str
    status: str  # "created", "running", "stopped", "destroyed"
    image: str
    ports: dict[int, int] = field(default_factory=dict)
    provider: str = "docker"
    url: str | None = None


@dataclass(frozen=True)
class ExecResult:
    """Result of executing a command in a container."""

    exit_code: int
    stdout: str
    stderr: str


class ContainerProvider(ABC):
    """Manages container lifecycle on a specific platform.

    Implementations exist for Docker (local) and Azure ACI (cloud).
    The interface is intentionally simple — create, start, stop, exec,
    destroy — so providers can map to any container runtime.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier for this provider (e.g. 'docker', 'azure')."""

    @abstractmethod
    async def create(self, config: ContainerConfig) -> ContainerInfo:
        """Create a container from *config* (does not start it)."""

    @abstractmethod
    async def start(self, container_id: str) -> bool:
        """Start a created/stopped container."""

    @abstractmethod
    async def stop(self, container_id: str) -> bool:
        """Stop a running container."""

    @abstractmethod
    async def destroy(self, container_id: str) -> bool:
        """Remove a container and its anonymous volumes."""

    @abstractmethod
    async def exec(
        self, container_id: str, command: str, timeout: float = 30.0
    ) -> ExecResult:
        """Execute a command inside a running container."""

    @abstractmethod
    async def get_info(self, container_id: str) -> ContainerInfo | None:
        """Get current info for a container, or None if not found."""

    @abstractmethod
    async def list_containers(self) -> list[ContainerInfo]:
        """List all containers managed by this provider."""

    @abstractmethod
    async def get_url(
        self, container_id: str, container_port: int
    ) -> str | None:
        """Get the accessible URL for a container port, or None."""
