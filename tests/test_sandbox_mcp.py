"""Tests for MCP config models, parsing, scope resolution, and filtering."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from hort.sandbox.mcp import (
    McpConfig,
    McpServerConfig,
    ToolFilter,
    build_claude_mcp_json,
    compute_disallowed_tools,
    filter_tools_list,
    is_tool_allowed,
    load_mcp_config,
    needs_proxy,
    parse_inline_mcp,
    resolve_servers,
)


# ── parse_inline_mcp ──────────────────────────────────────────────


def test_parse_inline_simple() -> None:
    name, cfg = parse_inline_mcp("fs=npx -y @mcp/filesystem /tmp")
    assert name == "fs"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "@mcp/filesystem", "/tmp"]


def test_parse_inline_no_args() -> None:
    name, cfg = parse_inline_mcp("myserver=mycommand")
    assert name == "myserver"
    assert cfg.command == "mycommand"
    assert cfg.args == []


def test_parse_inline_missing_equals() -> None:
    with pytest.raises(ValueError, match="Expected"):
        parse_inline_mcp("noequals")


def test_parse_inline_empty_command() -> None:
    with pytest.raises(ValueError, match="no command"):
        parse_inline_mcp("name=")


# ── load_mcp_config ───────────────────────────────────────────────


def test_load_config_full() -> None:
    data = {
        "mcpServers": {
            "fs": {
                "command": "npx",
                "args": ["-y", "@mcp/filesystem"],
                "env": {"HOME": "/tmp"},
                "scope": "outside",
                "toolFilter": {
                    "allow": ["read_file"],
                    "deny": ["write_file"],
                },
            },
            "git": {
                "command": "git-mcp",
                "scope": "inside",
            },
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        f.flush()
        config = load_mcp_config(f.name)

    assert "fs" in config.mcpServers
    assert "git" in config.mcpServers
    fs = config.mcpServers["fs"]
    assert fs.command == "npx"
    assert fs.scope == "outside"
    assert fs.tool_filter is not None
    assert fs.tool_filter.allow == ["read_file"]
    assert fs.tool_filter.deny == ["write_file"]
    assert fs.env == {"HOME": "/tmp"}

    git = config.mcpServers["git"]
    assert git.scope == "inside"
    assert git.tool_filter is None

    Path(f.name).unlink()


def test_load_config_minimal() -> None:
    data = {"mcpServers": {"s": {"command": "cmd"}}}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        f.flush()
        config = load_mcp_config(f.name)

    s = config.mcpServers["s"]
    assert s.command == "cmd"
    assert s.args == []
    assert s.env == {}
    assert s.scope == "auto"
    assert s.tool_filter is None
    Path(f.name).unlink()


# ── needs_proxy ───────────────────────────────────────────────────


def test_needs_proxy_container_outside() -> None:
    cfg = McpServerConfig(command="cmd", scope="outside")
    assert needs_proxy(cfg, container_mode=True) is True


def test_needs_proxy_container_auto() -> None:
    cfg = McpServerConfig(command="cmd", scope="auto")
    assert needs_proxy(cfg, container_mode=True) is True


def test_needs_proxy_container_inside() -> None:
    cfg = McpServerConfig(command="cmd", scope="inside")
    assert needs_proxy(cfg, container_mode=True) is False


def test_needs_proxy_local_no_filter() -> None:
    cfg = McpServerConfig(command="cmd")
    assert needs_proxy(cfg, container_mode=False) is False


def test_needs_proxy_local_deny_only() -> None:
    cfg = McpServerConfig(
        command="cmd",
        tool_filter=ToolFilter(deny=["bad_tool"]),
    )
    assert needs_proxy(cfg, container_mode=False) is False


def test_needs_proxy_local_allow_filter() -> None:
    cfg = McpServerConfig(
        command="cmd",
        tool_filter=ToolFilter(allow=["good_tool"]),
    )
    assert needs_proxy(cfg, container_mode=False) is True


# ── resolve_servers ───────────────────────────────────────────────


def test_resolve_local_all_direct() -> None:
    config = McpConfig(mcpServers={
        "a": McpServerConfig(command="a"),
        "b": McpServerConfig(command="b"),
    })
    direct, proxied = resolve_servers(config, container_mode=False)
    assert set(direct.keys()) == {"a", "b"}
    assert proxied == {}


def test_resolve_local_with_allow_filter() -> None:
    config = McpConfig(mcpServers={
        "a": McpServerConfig(command="a"),
        "b": McpServerConfig(
            command="b",
            tool_filter=ToolFilter(allow=["tool1"]),
        ),
    })
    direct, proxied = resolve_servers(config, container_mode=False)
    assert set(direct.keys()) == {"a"}
    assert set(proxied.keys()) == {"b"}


def test_resolve_container_split() -> None:
    config = McpConfig(mcpServers={
        "inside": McpServerConfig(command="i", scope="inside"),
        "outside": McpServerConfig(command="o", scope="outside"),
        "auto": McpServerConfig(command="a"),  # auto → proxied in container
    })
    direct, proxied = resolve_servers(config, container_mode=True)
    assert set(direct.keys()) == {"inside"}
    assert set(proxied.keys()) == {"outside", "auto"}


# ── build_claude_mcp_json ─────────────────────────────────────────


def test_build_json_direct_only() -> None:
    direct = {
        "fs": McpServerConfig(
            command="npx", args=["-y", "@mcp/fs"], env={"K": "V"}
        ),
    }
    result = build_claude_mcp_json(direct)
    assert result == {
        "mcpServers": {
            "fs": {
                "command": "npx",
                "args": ["-y", "@mcp/fs"],
                "env": {"K": "V"},
            }
        }
    }


def test_build_json_with_proxy_urls() -> None:
    direct = {"a": McpServerConfig(command="a")}
    proxy_urls = {"b": "http://host.docker.internal:9500/sse"}
    result = build_claude_mcp_json(direct, proxy_urls)
    assert result["mcpServers"]["a"]["command"] == "a"
    assert result["mcpServers"]["b"]["url"] == "http://host.docker.internal:9500/sse"


def test_build_json_no_env_omitted() -> None:
    direct = {"s": McpServerConfig(command="cmd")}
    result = build_claude_mcp_json(direct)
    assert "env" not in result["mcpServers"]["s"]


# ── compute_disallowed_tools ──────────────────────────────────────


def test_compute_disallowed_none() -> None:
    direct = {"s": McpServerConfig(command="cmd")}
    assert compute_disallowed_tools(direct) == []


def test_compute_disallowed_deny_list() -> None:
    direct = {
        "fs": McpServerConfig(
            command="cmd",
            tool_filter=ToolFilter(deny=["write_file", "delete_file"]),
        ),
        "other": McpServerConfig(command="cmd"),
    }
    result = compute_disallowed_tools(direct)
    assert set(result) == {"mcp__fs__write_file", "mcp__fs__delete_file"}


# ── filter_tools_list ─────────────────────────────────────────────

SAMPLE_TOOLS = [
    {"name": "read_file", "description": "Read"},
    {"name": "write_file", "description": "Write"},
    {"name": "delete_file", "description": "Delete"},
    {"name": "list_dir", "description": "List"},
]


def test_filter_allow() -> None:
    tf = ToolFilter(allow=["read_file", "list_dir"])
    result = filter_tools_list(SAMPLE_TOOLS, tf)
    names = [t["name"] for t in result]
    assert names == ["read_file", "list_dir"]


def test_filter_deny() -> None:
    tf = ToolFilter(deny=["delete_file"])
    result = filter_tools_list(SAMPLE_TOOLS, tf)
    names = [t["name"] for t in result]
    assert names == ["read_file", "write_file", "list_dir"]


def test_filter_allow_and_deny() -> None:
    tf = ToolFilter(allow=["read_file", "write_file"], deny=["write_file"])
    result = filter_tools_list(SAMPLE_TOOLS, tf)
    names = [t["name"] for t in result]
    assert names == ["read_file"]


def test_filter_no_filter() -> None:
    tf = ToolFilter()
    result = filter_tools_list(SAMPLE_TOOLS, tf)
    assert result == SAMPLE_TOOLS


# ── is_tool_allowed ───────────────────────────────────────────────


def test_allowed_no_filter() -> None:
    assert is_tool_allowed("anything", ToolFilter()) is True


def test_allowed_in_allow_list() -> None:
    assert is_tool_allowed("read", ToolFilter(allow=["read", "write"])) is True


def test_not_in_allow_list() -> None:
    assert is_tool_allowed("delete", ToolFilter(allow=["read"])) is False


def test_in_deny_list() -> None:
    assert is_tool_allowed("delete", ToolFilter(deny=["delete"])) is False


def test_not_in_deny_list() -> None:
    assert is_tool_allowed("read", ToolFilter(deny=["delete"])) is True


def test_in_allow_but_also_deny() -> None:
    tf = ToolFilter(allow=["read", "write"], deny=["write"])
    assert is_tool_allowed("read", tf) is True
    assert is_tool_allowed("write", tf) is False
