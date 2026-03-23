"""Extension system for openhort.

Provides abstract provider interfaces, a manifest model, a registry
for discovering and loading extensions, and the plugin ecosystem:

- **Types** — provider ABCs (Window, Capture, Input, Workspace, Action, Command, UI)
- **Plugin** — enhanced base class with context injection (store, files, config, scheduler)
- **Manifest** — extension.json model with features, jobs, intents, MCP, documents
- **Storage** — per-plugin key-value store and file store with TTL
- **Scheduler** — interval background jobs
- **MCP** — Model Context Protocol tool provision
- **Documents** — searchable document provision for AI
- **Intents** — Android-like URI content handlers
"""

from hort.ext.documents import DocumentDef, DocumentMixin
from hort.ext.file_store import FileInfo, LocalFileStore, PluginFileStore
from hort.ext.intents import IntentData, IntentHandler, IntentMixin
from hort.ext.manifest import (
    ExtensionManifest,
    FeatureToggle,
    IntentManifest,
    JobManifest,
)
from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase, PluginConfig, PluginContext
from hort.ext.registry import ExtensionRegistry
from hort.ext.scheduler import JobSpec, PluginScheduler, ScheduledMixin
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
    # Types (existing)
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
    # Manifest
    "ExtensionManifest",
    "ExtensionRegistry",
    "FeatureToggle",
    "IntentManifest",
    "JobManifest",
    # Plugin
    "PluginBase",
    "PluginConfig",
    "PluginContext",
    # Storage
    "PluginStore",
    "FilePluginStore",
    "PluginFileStore",
    "LocalFileStore",
    "FileInfo",
    # Scheduler
    "PluginScheduler",
    "JobSpec",
    "ScheduledMixin",
    # MCP
    "MCPMixin",
    "MCPToolDef",
    "MCPToolResult",
    # Documents
    "DocumentMixin",
    "DocumentDef",
    # Intents
    "IntentMixin",
    "IntentHandler",
    "IntentData",
]
