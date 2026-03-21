"""Extension system for openhort.

Provides abstract provider interfaces, a manifest model, and a registry
for discovering and loading extensions at runtime.
"""

from hort.ext.manifest import ExtensionManifest
from hort.ext.registry import ExtensionRegistry
from hort.ext.types import (
    ActionInfo,
    ActionProvider,
    ActionResult,
    CaptureProvider,
    CommandResult,
    CommandTarget,
    ExtensionBase,
    InputProvider,
    PlatformProvider,
    UIProvider,
    WindowProvider,
    WorkspaceInfo,
    WorkspaceProvider,
)

__all__ = [
    "ActionInfo",
    "ActionProvider",
    "ActionResult",
    "CaptureProvider",
    "CommandResult",
    "CommandTarget",
    "ExtensionBase",
    "ExtensionManifest",
    "ExtensionRegistry",
    "InputProvider",
    "PlatformProvider",
    "UIProvider",
    "WindowProvider",
    "WorkspaceInfo",
    "WorkspaceProvider",
]
