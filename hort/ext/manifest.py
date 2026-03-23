"""Extension manifest model (extension.json)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FeatureToggle(BaseModel):
    """A configurable feature that can be enabled/disabled at runtime."""

    model_config = ConfigDict(frozen=True)

    description: str = ""
    default: bool = True
    requires: list[str] = Field(default_factory=list)


class JobManifest(BaseModel):
    """Declarative interval job definition in the manifest."""

    model_config = ConfigDict(frozen=True)

    id: str
    method: str  # method name on the plugin class
    interval_seconds: float
    run_on_activate: bool = False
    enabled_feature: str = ""  # only run when this feature is enabled


class IntentManifest(BaseModel):
    """Declarative intent handler definition in the manifest."""

    model_config = ConfigDict(frozen=True)

    scheme: str  # e.g. "photo", "geo", "file", "text"
    mime_types: list[str] = Field(default_factory=lambda: ["*/*"])
    method: str  # method name on the plugin class
    description: str = ""


class ExtensionManifest(BaseModel):
    """Parsed ``extension.json`` manifest for a single extension.

    All new fields are optional with defaults — fully backward
    compatible with existing extensions.
    """

    model_config = ConfigDict(frozen=True)

    # === Core fields (existing) ===
    name: str
    version: str = "0.0.0"
    description: str = ""
    provider: str = "core"
    platforms: list[str] = Field(
        default_factory=lambda: ["darwin", "linux", "win32"]
    )
    capabilities: list[str] = Field(default_factory=list)
    python_dependencies: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    entry_point: str = ""  # "module:ClassName"
    path: str = ""  # Absolute path to extension directory (set during discovery)

    # === Plugin metadata ===
    author: str = ""
    license: str = ""
    homepage: str = ""
    icon: str = ""  # Phosphor icon class (e.g. "ph ph-thermometer")
    plugin_type: str = ""  # "platform", "connector", "monitor", "tool", ""

    # === Feature toggles ===
    features: dict[str, FeatureToggle] = Field(default_factory=dict)

    # === Interval jobs (declarative, merged with get_jobs() at runtime) ===
    jobs: list[JobManifest] = Field(default_factory=list)

    # === Intent handlers (declarative, merged with get_intent_handlers()) ===
    intents: list[IntentManifest] = Field(default_factory=list)

    # === MCP tools (flag — actual tools defined in code) ===
    mcp: bool = False

    # === Document provision (flag — actual docs defined in code) ===
    documents: bool = False

    # === UI ===
    ui_widgets: list[str] = Field(default_factory=list)
    ui_script: str = ""  # e.g. "static/panel.js"

    # === Dependencies ===
    depends_on: list[str] = Field(default_factory=list)
