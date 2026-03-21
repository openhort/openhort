"""Extension manifest model (extension.json)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtensionManifest(BaseModel):
    """Parsed ``extension.json`` manifest for a single extension."""

    model_config = ConfigDict(frozen=True)

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
