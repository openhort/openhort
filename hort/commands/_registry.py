"""Shared helper — access the llming registry from command handlers."""

from __future__ import annotations

from typing import Any

_registry_ref: list[Any] = [None]


def set_llming_registry(registry: Any) -> None:
    """Called once at startup to make the registry available to commands."""
    _registry_ref[0] = registry


def get_llming_registry() -> Any:
    """Get the llming registry (ExtensionRegistry)."""
    return _registry_ref[0]
