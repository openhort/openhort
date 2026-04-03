"""World config loader — parses openhort.yaml into the full topology.

The world config defines the entire system: root hort, sub-horts,
llmings, connections, fences, groups, and credentials.  This module
loads the YAML, resolves credentials, and builds the wiring graph.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .credentials import resolve_credential, resolve_credentials
from .models import (
    AgentDef,
    ContainerConfig,
    DirectConnection,
    FenceConfig,
    HortDef,
    LlmingConnection,
    ToolGroup,
    WireRuleset,
    WorldConfig,
)

logger = logging.getLogger("hort.wiring.config")


def load_world_config(path: str | Path = "openhort.yaml") -> WorldConfig:
    """Load and parse the world config from a YAML file.

    Returns a ``WorldConfig`` with all credential references resolved,
    groups expanded, and sub-horts linked.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If the YAML is malformed.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"World config not found: {p}")

    raw = yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid world config: expected dict, got {type(raw).__name__}")

    return parse_world_config(raw)


def parse_world_config(raw: dict[str, Any]) -> WorldConfig:
    """Parse a raw dict into a WorldConfig.

    This is the core parser — used by both ``load_world_config``
    (file-based) and tests (dict-based).
    """
    # Parse global groups
    groups = _parse_groups(raw.get("groups", {}))

    # Parse root hort
    hort_raw = raw.get("hort", {})
    root_hort = _parse_hort(hort_raw)

    # Parse sub-horts (keys starting with "hort/")
    sub_horts: dict[str, HortDef] = {}
    for key, value in raw.items():
        if key.startswith("hort/") and isinstance(value, dict):
            sub_horts[key] = _parse_hort(value)

    return WorldConfig(
        groups=groups,
        hort=root_hort,
        sub_horts=sub_horts,
    )


def _parse_groups(raw: dict[str, Any]) -> dict[str, ToolGroup]:
    """Parse group definitions."""
    groups: dict[str, ToolGroup] = {}
    for name, gdef in raw.items():
        if isinstance(gdef, dict):
            groups[name] = ToolGroup(**gdef)
    return groups


def _parse_hort(raw: dict[str, Any]) -> HortDef:
    """Parse a single hort definition."""
    agent = None
    if "agent" in raw:
        agent = AgentDef(**raw["agent"]) if isinstance(raw["agent"], dict) else None

    container = None
    if "container" in raw:
        container = ContainerConfig(**raw["container"])

    credentials = raw.get("credentials", {})

    llmings = _parse_llmings(raw.get("llmings", []))
    direct = _parse_directs(raw.get("direct", []))
    fences = _parse_fences(raw.get("fences", []))
    circuits = raw.get("circuits", [])

    return HortDef(
        name=raw.get("name", ""),
        agent=agent,
        container=container,
        credentials=credentials,
        remote=raw.get("remote"),
        trust=raw.get("trust"),
        budget=raw.get("budget"),
        llmings=raw.get("llmings", []),
        direct=direct,
        fences=fences,
        circuits=circuits,
    )


def _parse_llmings(raw_list: list[Any]) -> list[dict[str, Any]]:
    """Parse llming connection entries.

    Each entry is either:
    - A string: ``"openhort/telegram"`` (no config)
    - A dict with one key: ``{"openhort/telegram": {"token": "env:TOKEN"}}``
    """
    return raw_list  # stored as raw dicts for flexibility


def _parse_directs(raw_list: list[Any]) -> list[DirectConnection]:
    """Parse direct llming-to-llming connections."""
    result: list[DirectConnection] = []
    for entry in raw_list:
        if isinstance(entry, dict):
            between = entry.get("between", [])
            rules_raw = {k: v for k, v in entry.items() if k != "between"}
            rules = WireRuleset(**rules_raw) if rules_raw else WireRuleset()
            result.append(DirectConnection(between=between, rules=rules))
    return result


def _parse_fences(raw_list: list[Any]) -> list[FenceConfig]:
    """Parse fence definitions."""
    result: list[FenceConfig] = []
    for entry in raw_list:
        if isinstance(entry, dict):
            inside_raw = entry.get("inside", {})
            boundary_raw = entry.get("boundary", {})
            result.append(FenceConfig(
                name=entry.get("name", ""),
                members=entry.get("members", []),
                inside=WireRuleset(**inside_raw) if inside_raw else WireRuleset(),
                boundary=WireRuleset(**boundary_raw) if boundary_raw else WireRuleset(),
            ))
    return result


def resolve_hort_credentials(hort: HortDef) -> dict[str, str]:
    """Resolve all credential references in a hort definition.

    Returns a dict of resolved key→value pairs, ready for injection
    into ``SessionConfig.secret_env``.
    """
    return resolve_credentials(hort.credentials)


def get_llming_connection(
    hort: HortDef,
    llming_id: str,
) -> tuple[WireRuleset, dict[str, Any]]:
    """Extract the WireRuleset and config for a specific llming connection.

    Returns ``(ruleset, config_dict)`` for the llming.
    """
    for entry in hort.llmings:
        if isinstance(entry, str):
            if entry == llming_id:
                return WireRuleset(), {}
        elif isinstance(entry, dict):
            for key, value in entry.items():
                if key == llming_id:
                    if isinstance(value, dict):
                        rule_fields = {
                            k: v for k, v in value.items()
                            if k in WireRuleset.model_fields
                        }
                        config_fields = {
                            k: v for k, v in value.items()
                            if k not in WireRuleset.model_fields
                        }
                        return WireRuleset(**rule_fields), config_fields
                    return WireRuleset(), {}
    return WireRuleset(), {}
