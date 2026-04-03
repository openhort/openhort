"""Tool group resolution — auto-assignment and composition.

Groups categorize tools by their name patterns (read_*, send_*, etc.)
so users can assign permissions with ``allow_groups: [read]`` instead
of listing every tool by name.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from .models import ToolGroup

# ── Built-in groups (auto-detected from tool name verbs) ──────────

BUILTIN_GROUPS: dict[str, ToolGroup] = {
    "read": ToolGroup(
        description="Read-only operations — no data leaves, nothing changes",
        color="green",
        auto=["read_*", "get_*", "list_*", "search_*", "query", "glob", "grep", "view_*"],
    ),
    "write": ToolGroup(
        description="Modifications — changes data in place",
        color="yellow",
        auto=["write_*", "edit_*", "update_*", "create_*", "set_*"],
    ),
    "send": ToolGroup(
        description="Outbound — data leaves the system",
        color="orange",
        auto=["send_*", "post_*", "push_*", "forward_*", "export_*"],
    ),
    "destroy": ToolGroup(
        description="Destructive — permanent deletion or damage",
        color="red",
        auto=["delete_*", "drop_*", "truncate_*", "remove_*", "purge_*"],
    ),
}


def auto_assign_group(tool_name: str, groups: dict[str, ToolGroup] | None = None) -> str | None:
    """Auto-assign a tool to a group based on its name pattern.

    Checks custom groups first (by ``auto`` patterns), then built-in groups.
    Returns the group name, or None if no pattern matches.
    """
    all_groups = {**(groups or {}), **BUILTIN_GROUPS}
    for group_name, group in all_groups.items():
        if group.auto:
            for pattern in group.auto:
                if fnmatch.fnmatch(tool_name, pattern):
                    return group_name
    return None


def resolve_groups(
    group_defs: dict[str, ToolGroup],
    group_name: str,
    _visited: set[str] | None = None,
) -> set[str]:
    """Resolve a group to its full set of tool patterns.

    Handles ``include_groups`` (composition), ``add``, and ``remove``.
    Detects circular references via ``_visited``.

    Returns a set of tool name patterns (globs or exact names).
    """
    if _visited is None:
        _visited = set()
    if group_name in _visited:
        return set()
    _visited.add(group_name)

    all_defs = {**BUILTIN_GROUPS, **group_defs}
    group = all_defs.get(group_name)
    if group is None:
        return set()

    tools: set[str] = set()

    # Start with included groups
    if group.include_groups:
        for inc in group.include_groups:
            tools |= resolve_groups(group_defs, inc, _visited)

    # Add auto patterns
    if group.auto:
        tools |= set(group.auto)

    # Add explicit tools
    if group.tools:
        tools |= set(group.tools)

    # Add individual tools
    if group.add:
        tools |= set(group.add)

    # Remove individual tools
    if group.remove:
        tools -= set(group.remove)

    return tools


def is_tool_in_group(
    tool_name: str,
    group_name: str,
    group_defs: dict[str, ToolGroup] | None = None,
) -> bool:
    """Check if a tool matches any pattern in a resolved group."""
    patterns = resolve_groups(group_defs or {}, group_name)
    return any(fnmatch.fnmatch(tool_name, p) for p in patterns)
