"""Container environment management for openhort.

Provides a provider-agnostic interface for creating, running, and
managing containers locally (Docker) or in the cloud (Azure ACI).
"""

from hort.containers.base import (
    ContainerConfig,
    ContainerInfo,
    ContainerProvider,
    ExecResult,
    MountConfig,
)
from hort.containers.registry import ContainerRegistry

__all__ = [
    "ContainerConfig",
    "ContainerInfo",
    "ContainerProvider",
    "ContainerRegistry",
    "ExecResult",
    "MountConfig",
]
