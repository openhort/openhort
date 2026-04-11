"""Structured hort configuration — parses llmings, groups, users, relations.

Reads from the same ``hort-config.yaml`` as the legacy config store but
interprets the new top-level sections:

- ``hort:`` — identity (name, device_uid)
- ``llmings:`` — all active llmings with type + config + envoy
- ``groups:`` — tool isolation (colors) + user permissions (roles)
- ``users:`` — identity matching + group membership
- ``relations:`` — inter-group data flow rules

Backward compatible: legacy flat keys (``connector.cloud``, ``telegram-connector``,
etc.) continue to work via ``get_store()``. The new sections are additive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def hort_data_dir() -> Path:
    """Return the instance-specific data directory.

    When ``HORT_INSTANCE_NAME`` is set, data is stored under
    ``~/.hort/instances/{name}/`` to isolate multiple instances on one machine.
    Otherwise falls back to ``~/.hort/`` (single-instance default).
    """
    import os
    instance = os.environ.get("HORT_INSTANCE_NAME", "")
    if instance:
        return Path(f"~/.hort/instances/{instance}").expanduser()
    return Path("~/.hort").expanduser()


@dataclass
class LlmingConfig:
    """Configuration for a single llming."""

    name: str
    type: str
    config: dict[str, Any] = field(default_factory=dict)
    envoy: dict[str, Any] | None = None  # container/wire config for remote execution


@dataclass
class GroupConfig:
    """A group definition — can be tool isolation, user role, or both."""

    name: str
    # Tool isolation (color groups)
    color: str = ""
    llmings: dict[str, Any] = field(default_factory=dict)  # llming_name: [capabilities] or "all"
    taint: str = ""
    block_taint: list[str] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    # User permissions (role groups)
    powers: dict[str, Any] = field(default_factory=dict)  # {allow: all} or {allow: {llming: [tools]}}
    pulse: dict[str, Any] = field(default_factory=dict)
    session: str = ""  # "shared", "isolated", or custom name
    wire: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserConfig:
    """A user definition with identity matching and group membership."""

    name: str
    groups: list[str] = field(default_factory=list)
    match: dict[str, str] = field(default_factory=dict)  # connector_type: identity


@dataclass
class RelationConfig:
    """A relation between two groups."""

    groups: list[str] = field(default_factory=list)
    type: str = "isolated"  # isolated, mutual, reads, delegates
    direction: str = ""  # e.g. "reporting -> erp"


@dataclass
class HortConfig:
    """Parsed structured hort configuration."""

    # Identity
    name: str = ""
    device_uid: str = "auto"

    # Llmings
    llmings: dict[str, LlmingConfig] = field(default_factory=dict)

    # Groups (unified: tool isolation + user roles)
    groups: dict[str, GroupConfig] = field(default_factory=dict)

    # Users
    users: dict[str, UserConfig] = field(default_factory=dict)

    # Relations between groups
    relations: list[RelationConfig] = field(default_factory=list)

    def get_llming(self, name: str) -> LlmingConfig | None:
        return self.llmings.get(name)

    def get_group(self, name: str) -> GroupConfig | None:
        return self.groups.get(name)

    def get_user_by_match(self, connector: str, identity: str) -> UserConfig | None:
        """Find a user by their connector identity (e.g., telegram: alice_dev)."""
        for user in self.users.values():
            match_val = user.match.get(connector, "")
            if match_val == identity:
                return user
            if match_val == "*":  # wildcard match
                return user
        return None

    def get_user_groups(self, user: UserConfig) -> list[GroupConfig]:
        """Get all group configs for a user."""
        return [self.groups[g] for g in user.groups if g in self.groups]

    def get_relation(self, group_a: str, group_b: str) -> RelationConfig | None:
        """Find the relation between two groups, if any."""
        for rel in self.relations:
            if set(rel.groups) == {group_a, group_b}:
                return rel
        return None

    def is_mutual(self, group_a: str, group_b: str) -> bool:
        """Check if two groups have a mutual relation."""
        rel = self.get_relation(group_a, group_b)
        return rel is not None and rel.type == "mutual"


def load_hort_config(path: str | Path = "hort-config.yaml") -> HortConfig:
    """Load and parse the structured hort configuration."""
    import yaml

    p = Path(path)
    if not p.exists():
        logger.info("No hort-config.yaml found, using defaults")
        return HortConfig()

    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except Exception as e:
        logger.warning("Failed to parse %s: %s", path, e)
        return HortConfig()

    config = HortConfig()

    # Hort identity
    hort_section = raw.get("hort", {})
    if isinstance(hort_section, dict):
        config.name = hort_section.get("name", "")
        config.device_uid = hort_section.get("device_uid", "auto")

    # Llmings
    llmings_section = raw.get("llmings", {})
    if isinstance(llmings_section, dict):
        for name, cfg in llmings_section.items():
            if not isinstance(cfg, dict):
                continue
            config.llmings[name] = LlmingConfig(
                name=name,
                type=cfg.get("type", ""),
                config=cfg.get("config", {}),
                envoy=cfg.get("envoy"),
            )

    # Groups
    groups_section = raw.get("groups", {})
    if isinstance(groups_section, dict):
        for name, cfg in groups_section.items():
            if not isinstance(cfg, dict):
                continue
            config.groups[name] = GroupConfig(
                name=name,
                color=cfg.get("color", ""),
                llmings=cfg.get("llmings", {}),
                taint=cfg.get("taint", ""),
                block_taint=cfg.get("block_taint", []),
                filters=cfg.get("filters", []),
                powers=cfg.get("powers", {}),
                pulse=cfg.get("pulse", {}),
                session=cfg.get("session", ""),
                wire=cfg.get("wire", {}),
            )

    # Users
    users_section = raw.get("users", {})
    if isinstance(users_section, dict):
        for name, cfg in users_section.items():
            if not isinstance(cfg, dict):
                continue
            config.users[name] = UserConfig(
                name=name,
                groups=cfg.get("groups", []),
                match=cfg.get("match", {}),
            )

    # Relations
    relations_section = raw.get("relations", [])
    if isinstance(relations_section, list):
        for rel in relations_section:
            if not isinstance(rel, dict):
                continue
            config.relations.append(RelationConfig(
                groups=rel.get("groups", []),
                type=rel.get("type", "isolated"),
                direction=rel.get("direction", ""),
            ))

    logger.info(
        "Loaded hort config: %d llmings, %d groups, %d users, %d relations",
        len(config.llmings), len(config.groups), len(config.users), len(config.relations),
    )
    return config


# ===== Singleton =====

_hort_config: HortConfig | None = None


def get_hort_config() -> HortConfig:
    """Get the parsed hort configuration (singleton)."""
    global _hort_config
    if _hort_config is None:
        _hort_config = load_hort_config()
    return _hort_config


def reset_hort_config() -> None:
    """Reset the singleton (for testing)."""
    global _hort_config
    _hort_config = None
