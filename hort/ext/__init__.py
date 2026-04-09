"""Extension system for openhort.

Provides abstract provider interfaces, a manifest model, a registry
for discovering and loading extensions, and per-instance storage.

All llmings inherit from ``LlmingBase`` (hort.llming). The ext package
provides the infrastructure they run on: registry, manifest, storage,
scheduler, MCP data types, connector framework.
"""

from hort.ext.file_store import FileInfo, LocalFileStore, PluginFileStore
from hort.ext.manifest import (
    ExtensionManifest,
    FeatureToggle,
    IntentManifest,
    JobManifest,
)
from hort.ext.credentials import CredentialStore
from hort.ext.mcp import MCPToolDef, MCPToolResult
from hort.ext.skills import SoulSection
from hort.ext.registry import ExtensionRegistry
from hort.ext.scheduler import JobSpec, LlmingScheduler, PluginScheduler
from hort.ext.store import FilePluginStore, PluginStore
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
    # Types
    "ActionInfo",
    "ActionProvider",
    "ActionResult",
    "CaptureProvider",
    "CommandResult",
    "CommandTarget",
    "ExtensionBase",
    "InputProvider",
    "PlatformProvider",
    "UIProvider",
    "WindowProvider",
    "WorkspaceInfo",
    "WorkspaceProvider",
    # Credentials
    "CredentialStore",
    # Manifest
    "ExtensionManifest",
    "ExtensionRegistry",
    "FeatureToggle",
    "IntentManifest",
    "JobManifest",
    # Storage
    "PluginStore",
    "FilePluginStore",
    "PluginFileStore",
    "LocalFileStore",
    "FileInfo",
    # Scheduler
    "LlmingScheduler",
    "PluginScheduler",  # backward-compatible alias
    "JobSpec",
    # MCP data types
    "MCPToolDef",
    "MCPToolResult",
    # Skills
    "SoulSection",
]
