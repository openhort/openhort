"""Container registry — tracks containers across providers."""

from __future__ import annotations

from hort.containers.base import ContainerInfo, ContainerProvider


class ContainerRegistry:
    """Tracks all active containers and their providers.

    Singleton — use ``ContainerRegistry.get()`` to access.
    """

    _instance: ContainerRegistry | None = None

    def __init__(self) -> None:
        self._containers: dict[str, ContainerInfo] = {}
        self._providers: dict[str, ContainerProvider] = {}

    @classmethod
    def get(cls) -> ContainerRegistry:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    def register_provider(self, provider: ContainerProvider) -> None:
        """Register a container provider by name."""
        self._providers[provider.provider_name] = provider

    def get_provider(self, name: str) -> ContainerProvider | None:
        """Get a registered provider by name."""
        return self._providers.get(name)

    def track(self, info: ContainerInfo) -> None:
        """Track a container."""
        self._containers[info.container_id] = info

    def untrack(self, container_id: str) -> ContainerInfo | None:
        """Stop tracking a container."""
        return self._containers.pop(container_id, None)

    def get_container(self, container_id: str) -> ContainerInfo | None:
        """Get a tracked container by ID."""
        return self._containers.get(container_id)

    def list_all(self) -> list[ContainerInfo]:
        """List all tracked containers."""
        return list(self._containers.values())

    def provider_for(self, container_id: str) -> ContainerProvider | None:
        """Get the provider for a tracked container."""
        info = self.get_container(container_id)
        if info is None:
            return None
        return self._providers.get(info.provider)
