"""Skills — composable prompt fragments from SOUL.md files.

Each extension can provide a ``SOUL.md`` that teaches the chat agent
when and how to use its tools. The file is plain Markdown — readable
on GitHub, editable by users, no special syntax.

Structure::

    # Extension Name

    Preamble text (always included).

    ## Chapter Name

    Feature: feature_toggle_name
    Tool: screenshot
    Tool: list_windows

    Instructions for when/how to use these tools...

    ## Another Chapter

    Feature: another_feature
    Tool: click

    More instructions...

Chapters are split on ``## `` headings. ``Feature:`` and ``Tool:``
lines are parsed as metadata and stripped from the instruction text.
When a feature is disabled, the chapter and its tools disappear from
the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SoulSection:
    """A chapter from a SOUL.md file."""

    title: str
    feature: str = ""
    tools: list[str] = field(default_factory=list)
    content: str = ""
    plugin_id: str = ""


def load_soul(soul_path: Path, plugin_id: str = "") -> tuple[str, list[SoulSection]]:
    """Load and parse a SOUL.md file.

    Returns:
        (preamble, sections) — preamble is text before the first ``## ``,
        sections are the parsed chapters.
    """
    if not soul_path.exists():
        return "", []

    text = soul_path.read_text(encoding="utf-8").strip()

    # Split on ## headings
    parts = re.split(r"^(## .+)$", text, flags=re.MULTILINE)

    # parts[0] = preamble (before first ##)
    # parts[1] = "## Title", parts[2] = body, parts[3] = "## Title", parts[4] = body, ...
    preamble = parts[0].strip()
    # Strip the # heading from preamble (it's the extension title)
    preamble_lines = preamble.split("\n")
    if preamble_lines and preamble_lines[0].startswith("# "):
        preamble_lines = preamble_lines[1:]
    preamble = "\n".join(preamble_lines).strip()

    sections: list[SoulSection] = []
    i = 1
    while i < len(parts) - 1:
        title = parts[i].removeprefix("## ").strip()
        body = parts[i + 1].strip()
        i += 2

        # Extract Feature: and Tool: lines from the body
        feature = ""
        tools: list[str] = []
        content_lines: list[str] = []

        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Feature:"):
                feature = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("Tool:"):
                tools.append(stripped.split(":", 1)[1].strip())
            else:
                content_lines.append(line)

        # Remove leading blank lines from content
        content = "\n".join(content_lines).strip()

        sections.append(SoulSection(
            title=title,
            feature=feature,
            tools=tools,
            content=content,
            plugin_id=plugin_id,
        ))

    return preamble, sections


def build_system_prompt(
    preamble: str,
    sections: list[SoulSection],
    base_prompt: str = "",
    is_feature_enabled: Any = None,
) -> tuple[str, list[str]]:
    """Build a system prompt from a SOUL.md's preamble and sections.

    Args:
        preamble: Always-included text from the SOUL.md header.
        sections: Parsed chapters.
        base_prompt: Optional base prompt prepended before everything.
        is_feature_enabled: Optional ``(plugin_id, feature) -> bool``.
            If None, all sections are included.

    Returns:
        (system_prompt, disabled_tools) — disabled_tools contains
        MCP tool patterns for ``--disallowedTools``.
    """
    parts: list[str] = []
    disabled_tools: list[str] = []

    if base_prompt:
        parts.append(base_prompt.strip())

    if preamble:
        parts.append(preamble)

    for section in sections:
        if section.feature and is_feature_enabled:
            if not is_feature_enabled(section.plugin_id, section.feature):
                for tool in section.tools:
                    disabled_tools.append(
                        f"mcp__openhort__{section.plugin_id}__{tool}"
                    )
                continue

        parts.append(f"## {section.title}\n\n{section.content}")

    return "\n\n".join(parts), disabled_tools
