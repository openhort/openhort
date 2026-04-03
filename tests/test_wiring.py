"""End-to-end tests for the wiring model.

Tests multiple world configurations covering:
- Simple setups (root hort + llmings)
- Sub-horts with Docker isolation
- Fences (virtual boundaries, overlapping)
- Taint blocking across boundaries
- Credential resolution (env:, vault:, file:)
- Group-based permissions (built-in + custom)
- Rule precedence (hort > fence > llming > direct)
- Complete real-world scenarios
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hort.wiring import (
    BUILTIN_GROUPS,
    ConversationTaint,
    CredentialRef,
    FenceConfig,
    TaintedMessage,
    ToolGroup,
    WireEvaluator,
    WireRuleset,
    WorldConfig,
    auto_assign_group,
    resolve_credential,
    resolve_groups,
)
from hort.wiring.config import (
    get_llming_connection,
    load_world_config,
    parse_world_config,
    resolve_hort_credentials,
)
from hort.wiring.models import DirectConnection, HortDef


# ── Credential Resolution ─────────────────────────────────────────


class TestCredentialResolution:
    """Test env:, vault:, file: credential schemes."""

    def test_env_resolution(self) -> None:
        with patch.dict(os.environ, {"MY_TOKEN": "secret123"}):
            assert resolve_credential("env:MY_TOKEN") == "secret123"

    def test_env_missing_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="not set"):
                resolve_credential("env:NONEXISTENT_VAR")

    def test_file_resolution(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("my-secret-value\nextra-line\n")
        assert resolve_credential(f"file:{secret_file}") == "my-secret-value"

    def test_file_missing_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            resolve_credential("file:/nonexistent/path")

    def test_vault_resolution(self, tmp_path: Path) -> None:
        vault_dir = tmp_path / ".openhort" / "vault"
        vault_dir.mkdir(parents=True)
        (vault_dir / "azure.client-id").write_text("my-client-id\n")
        with patch("hort.wiring.credentials.Path.home", return_value=tmp_path):
            assert resolve_credential("vault:azure/client-id") == "my-client-id"

    def test_vault_missing_raises(self, tmp_path: Path) -> None:
        with patch("hort.wiring.credentials.Path.home", return_value=tmp_path):
            with pytest.raises(ValueError, match="not found"):
                resolve_credential("vault:nonexistent/secret")

    def test_plain_string_passthrough(self) -> None:
        assert resolve_credential("literal-value") == "literal-value"

    def test_credential_ref_model(self) -> None:
        ref = CredentialRef(value="env:MY_TOKEN")
        assert ref.is_env()
        assert not ref.is_vault()
        assert ref.key == "MY_TOKEN"

        ref2 = CredentialRef(value="vault:azure/client-id")
        assert ref2.is_vault()
        assert ref2.key == "azure/client-id"


# ── Tool Groups ───────────────────────────────────────────────────


class TestToolGroups:
    """Test auto-assignment and group composition."""

    def test_builtin_read_group(self) -> None:
        assert auto_assign_group("read_email") == "read"
        assert auto_assign_group("get_balance") == "read"
        assert auto_assign_group("list_calendars") == "read"
        assert auto_assign_group("search_contacts") == "read"

    def test_builtin_write_group(self) -> None:
        assert auto_assign_group("write_file") == "write"
        assert auto_assign_group("create_event") == "write"
        assert auto_assign_group("update_record") == "write"
        assert auto_assign_group("edit_document") == "write"

    def test_builtin_send_group(self) -> None:
        assert auto_assign_group("send_email") == "send"
        assert auto_assign_group("post_message") == "send"
        assert auto_assign_group("push_notification") == "send"
        assert auto_assign_group("forward_email") == "send"

    def test_builtin_destroy_group(self) -> None:
        assert auto_assign_group("delete_email") == "destroy"
        assert auto_assign_group("drop_table") == "destroy"
        assert auto_assign_group("truncate_log") == "destroy"
        assert auto_assign_group("remove_user") == "destroy"

    def test_unknown_tool_no_group(self) -> None:
        assert auto_assign_group("do_something") is None
        assert auto_assign_group("magic_tool") is None

    def test_custom_group_overrides(self) -> None:
        custom = {
            "safe": ToolGroup(auto=["do_*", "magic_*"]),
        }
        assert auto_assign_group("do_something", custom) == "safe"
        assert auto_assign_group("magic_tool", custom) == "safe"

    def test_resolve_group_with_includes(self) -> None:
        groups = {
            "level-1": ToolGroup(auto=["read_*", "get_*"]),
            "level-2": ToolGroup(include_groups=["level-1"], auto=["create_*"]),
        }
        patterns = resolve_groups(groups, "level-2")
        assert "read_*" in patterns
        assert "get_*" in patterns
        assert "create_*" in patterns

    def test_resolve_group_with_add_remove(self) -> None:
        groups = {
            "custom": ToolGroup(
                include_groups=["read"],
                add=["special_tool"],
                remove=["search_*"],
            ),
        }
        patterns = resolve_groups(groups, "custom")
        assert "special_tool" in patterns
        assert "read_*" in patterns
        assert "search_*" not in patterns

    def test_circular_group_reference(self) -> None:
        groups = {
            "a": ToolGroup(include_groups=["b"]),
            "b": ToolGroup(include_groups=["a"]),
        }
        # Should not infinite loop
        patterns = resolve_groups(groups, "a")
        assert isinstance(patterns, set)


# ── WireRuleset ───────────────────────────────────────────────────


class TestWireRuleset:
    """Test the unified ruleset model."""

    def test_defaults_are_permissive(self) -> None:
        r = WireRuleset()
        assert r.allow is None
        assert r.deny is None
        assert r.taint is None
        assert r.block_taint is None

    def test_taint_labels_string(self) -> None:
        r = WireRuleset(taint="source:sap")
        assert r.taint_labels() == ["source:sap"]

    def test_taint_labels_list(self) -> None:
        r = WireRuleset(taint=["source:sap", "content:financial"])
        assert r.taint_labels() == ["source:sap", "content:financial"]

    def test_taint_labels_none(self) -> None:
        r = WireRuleset()
        assert r.taint_labels() == []

    def test_extra_fields_allowed(self) -> None:
        r = WireRuleset(name="test", custom_field="hello")
        assert r.name == "test"


# ── Wire Evaluator ────────────────────────────────────────────────


class TestWireEvaluator:
    """Test rule evaluation with stacked rulesets."""

    def test_empty_rulesets_allow_everything(self) -> None:
        ev = WireEvaluator()
        d = ev.check_tool("anything", [])
        assert d.allowed

    def test_explicit_deny(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(deny=["send_*"])
        d = ev.check_tool("send_email", [("wire", r)])
        assert not d.allowed
        assert "denied by pattern" in d.reason

    def test_explicit_allow_blocks_unlisted(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(allow=["read_*"])
        d = ev.check_tool("send_email", [("wire", r)])
        assert not d.allowed
        assert "not in allow list" in d.reason

    def test_explicit_allow_permits_match(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(allow=["read_*", "send_*"])
        d = ev.check_tool("read_email", [("wire", r)])
        assert d.allowed

    def test_group_deny(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(deny_groups=["destroy"])
        d = ev.check_tool("delete_email", [("wire", r)])
        assert not d.allowed
        assert "group 'destroy'" in d.reason

    def test_group_allow(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(allow_groups=["read"])
        d = ev.check_tool("read_email", [("wire", r)])
        assert d.allowed

    def test_group_allow_blocks_other(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(allow_groups=["read"])
        d = ev.check_tool("send_email", [("wire", r)])
        assert not d.allowed

    def test_taint_blocking(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(block_taint=["source:sap"])
        d = ev.check_tool("send_email", [("wire", r)], current_taint={"source:sap"})
        assert not d.allowed
        assert "Tainted data blocked" in d.reason

    def test_taint_no_block_when_clean(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(block_taint=["source:sap"])
        d = ev.check_tool("send_email", [("wire", r)], current_taint=set())
        assert d.allowed

    def test_taint_collection(self) -> None:
        ev = WireEvaluator()
        r = WireRuleset(taint=["source:o365", "content:email"])
        d = ev.check_tool("read_email", [("wire", r)])
        assert d.allowed
        assert "source:o365" in d.taint_labels
        assert "content:email" in d.taint_labels

    def test_stacked_rulesets_all_must_pass(self) -> None:
        ev = WireEvaluator()
        r1 = WireRuleset(allow_groups=["read", "send"])  # outer: allows read+send
        r2 = WireRuleset(deny_groups=["send"])            # inner: denies send
        d = ev.check_tool("send_email", [("hort", r1), ("llming", r2)])
        assert not d.allowed
        assert d.layer == "llming"

    def test_stacked_rulesets_outer_blocks_first(self) -> None:
        ev = WireEvaluator()
        r1 = WireRuleset(deny_groups=["send"])   # outer denies
        r2 = WireRuleset()                       # inner permissive
        d = ev.check_tool("send_email", [("hort", r1), ("llming", r2)])
        assert not d.allowed
        assert d.layer == "hort"

    def test_custom_groups(self) -> None:
        custom = {"safe": ToolGroup(tools=["my_tool", "other_tool"])}
        ev = WireEvaluator(groups=custom)
        r = WireRuleset(allow_groups=["safe"])
        d = ev.check_tool("my_tool", [("wire", r)])
        assert d.allowed
        d2 = ev.check_tool("unknown_tool", [("wire", r)])
        assert not d2.allowed


# ── Fence Evaluation ──────────────────────────────────────────────


class TestFenceEvaluation:
    """Test fence boundary and inside rules."""

    def test_both_inside_fence_uses_inside_rules(self) -> None:
        ev = WireEvaluator()
        fence = FenceConfig(
            name="safe",
            members=["telegram", "github"],
            inside=WireRuleset(allow_groups=["read", "write"]),
            boundary=WireRuleset(allow_groups=["read"]),
        )
        d = ev.check_tool(
            "create_pr", [], fences=[fence],
            source_llming="telegram", target_llming="github",
        )
        assert d.allowed

    def test_crossing_fence_uses_boundary_rules(self) -> None:
        ev = WireEvaluator()
        fence = FenceConfig(
            name="sensitive",
            members=["sap"],
            inside=WireRuleset(),
            boundary=WireRuleset(deny_groups=["send"]),
        )
        d = ev.check_tool(
            "send_email", [], fences=[fence],
            source_llming="sap", target_llming="email-tool",
        )
        assert not d.allowed
        assert "fence:sensitive:boundary" in d.layer

    def test_neither_in_fence_ignores(self) -> None:
        ev = WireEvaluator()
        fence = FenceConfig(
            name="irrelevant",
            members=["something-else"],
            boundary=WireRuleset(deny=["*"]),
        )
        d = ev.check_tool(
            "read_email", [], fences=[fence],
            source_llming="telegram", target_llming="o365",
        )
        assert d.allowed

    def test_overlapping_fences_intersection(self) -> None:
        ev = WireEvaluator()
        fence1 = FenceConfig(
            name="chat",
            members=["telegram", "o365"],
            inside=WireRuleset(allow_groups=["read", "send"]),
        )
        fence2 = FenceConfig(
            name="sensitive",
            members=["o365", "sap"],
            boundary=WireRuleset(deny_groups=["send"]),
        )
        # telegram is in "chat" only
        # o365 is in both "chat" and "sensitive"
        # send from telegram→o365: chat allows, sensitive boundary denies
        d = ev.check_tool(
            "send_email", [], fences=[fence1, fence2],
            source_llming="telegram", target_llming="o365",
        )
        # fence2 boundary should block (telegram outside sensitive, o365 inside)
        assert not d.allowed

    def test_fence_taint_on_boundary(self) -> None:
        ev = WireEvaluator()
        fence = FenceConfig(
            name="sensitive",
            members=["sap"],
            boundary=WireRuleset(taint="source:sensitive"),
        )
        d = ev.check_tool(
            "get_balance", [], fences=[fence],
            source_llming="agent", target_llming="sap",
        )
        assert d.allowed
        assert "source:sensitive" in d.taint_labels


# ── World Config Parsing ──────────────────────────────────────────


class TestWorldConfigParsing:
    """Test parsing complete world configs from YAML dicts."""

    def test_minimal_config(self) -> None:
        raw = {
            "hort": {
                "name": "Test",
                "llmings": [
                    {"openhort/telegram": {}},
                ],
            },
        }
        world = parse_world_config(raw)
        assert world.hort.name == "Test"
        assert len(world.hort.llmings) == 1

    def test_sub_horts(self) -> None:
        raw = {
            "hort": {
                "name": "Main",
                "llmings": [
                    {"hort/o365": {"taint": "source:o365"}},
                ],
            },
            "hort/o365": {
                "name": "O365 Hull",
                "container": {"network": ["graph.microsoft.com"]},
                "credentials": {"CLIENT_ID": "env:AZURE_CLIENT_ID"},
                "llmings": [
                    {"microsoft/office365": {"allow_groups": ["read"]}},
                ],
            },
        }
        world = parse_world_config(raw)
        assert "hort/o365" in world.sub_horts
        o365 = world.sub_horts["hort/o365"]
        assert o365.name == "O365 Hull"
        assert o365.container is not None
        assert "graph.microsoft.com" in o365.container.network

    def test_fences_parsed(self) -> None:
        raw = {
            "hort": {
                "name": "Main",
                "llmings": [],
                "fences": [
                    {
                        "name": "safe",
                        "members": ["telegram", "github"],
                        "inside": {"allow_groups": ["read", "write"]},
                        "boundary": {"taint": "source:safe"},
                    },
                ],
            },
        }
        world = parse_world_config(raw)
        assert len(world.hort.fences) == 1
        fence = world.hort.fences[0]
        assert fence.name == "safe"
        assert fence.members == ["telegram", "github"]
        assert fence.inside.allow_groups == ["read", "write"]

    def test_direct_connections_parsed(self) -> None:
        raw = {
            "hort": {
                "name": "Main",
                "llmings": [],
                "direct": [
                    {
                        "between": ["telegram", "o365"],
                        "allow": ["email_arrived"],
                    },
                ],
            },
        }
        world = parse_world_config(raw)
        assert len(world.hort.direct) == 1
        assert world.hort.direct[0].between == ["telegram", "o365"]
        assert world.hort.direct[0].rules.allow == ["email_arrived"]

    def test_global_groups(self) -> None:
        raw = {
            "groups": {
                "safe": {"auto": ["read_*"], "color": "green"},
                "code-safe": {"include_groups": ["safe"], "add": ["create_pr"]},
            },
            "hort": {"name": "Main"},
        }
        world = parse_world_config(raw)
        assert "safe" in world.groups
        assert "code-safe" in world.groups
        assert world.groups["code-safe"].include_groups == ["safe"]

    def test_get_llming_connection(self) -> None:
        hort = HortDef(
            name="Test",
            llmings=[
                {"openhort/github": {
                    "allow_groups": ["read"],
                    "deny_groups": ["destroy"],
                    "taint": "source:github",
                    "token": "env:GH_TOKEN",
                }},
            ],
        )
        ruleset, config = get_llming_connection(hort, "openhort/github")
        assert ruleset.allow_groups == ["read"]
        assert ruleset.deny_groups == ["destroy"]
        assert ruleset.taint == "source:github"
        assert config.get("token") == "env:GH_TOKEN"


# ── Complete Scenario Tests ───────────────────────────────────────


class TestScenarioSimpleDesktop:
    """Scenario: Simple desktop with Telegram + GitHub + shell."""

    @pytest.fixture()
    def world(self) -> WorldConfig:
        return parse_world_config({
            "hort": {
                "name": "My Desktop",
                "agent": {"provider": "claude-code", "model": "claude-sonnet-4-6"},
                "container": {"memory": "4g", "cpus": 4},
                "llmings": [
                    {"openhort/telegram": {"token": "env:TG_TOKEN"}},
                    {"openhort/github": {
                        "allow_groups": ["read", "write"],
                        "deny_groups": ["destroy"],
                    }},
                    {"openhort/shell": {
                        "allow_groups": ["read"],
                        "deny_groups": ["send", "destroy"],
                    }},
                ],
            },
        })

    def test_github_read_allowed(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/github")
        d = ev.check_tool("read_file", [("llming", ruleset)])
        assert d.allowed

    def test_github_create_pr_allowed(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/github")
        d = ev.check_tool("create_pr", [("llming", ruleset)])
        assert d.allowed

    def test_github_delete_blocked(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/github")
        d = ev.check_tool("delete_repo", [("llming", ruleset)])
        assert not d.allowed

    def test_shell_read_allowed(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/shell")
        d = ev.check_tool("read_output", [("llming", ruleset)])
        assert d.allowed

    def test_shell_send_blocked(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/shell")
        d = ev.check_tool("send_data", [("llming", ruleset)])
        assert not d.allowed


class TestScenarioSubHortWithTaint:
    """Scenario: O365 and SAP in separate hulls with taint isolation."""

    @pytest.fixture()
    def world(self) -> WorldConfig:
        return parse_world_config({
            "hort": {
                "name": "Office Assistant",
                "agent": {"provider": "claude-code"},
                "llmings": [
                    {"openhort/telegram": {}},
                    {"hort/o365": {"taint": "source:o365", "block_taint": ["source:sap"]}},
                    {"hort/sap": {"taint": "source:sap", "block_taint": ["source:o365"]}},
                    {"openhort/shell": {"block_taint": ["source:o365", "source:sap"]}},
                ],
            },
            "hort/o365": {
                "container": {"network": ["graph.microsoft.com"]},
                "credentials": {"CLIENT_ID": "env:AZURE_CLIENT_ID"},
                "llmings": [
                    {"microsoft/office365": {
                        "allow_groups": ["read"],
                        "deny_groups": ["send", "destroy"],
                    }},
                ],
            },
            "hort/sap": {
                "container": {"network": ["sap.internal:8443"]},
                "llmings": [
                    {"sap/connector": {
                        "allow_groups": ["read"],
                        "deny_groups": ["write", "send", "destroy"],
                    }},
                ],
            },
        })

    def test_o365_read_allowed(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        hort_rule, _ = get_llming_connection(world.hort, "hort/o365")
        inner_rule, _ = get_llming_connection(
            world.sub_horts["hort/o365"], "microsoft/office365",
        )
        d = ev.check_tool("read_email", [("hort", hort_rule), ("llming", inner_rule)])
        assert d.allowed
        assert "source:o365" in d.taint_labels

    def test_o365_send_blocked_by_inner(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        hort_rule, _ = get_llming_connection(world.hort, "hort/o365")
        inner_rule, _ = get_llming_connection(
            world.sub_horts["hort/o365"], "microsoft/office365",
        )
        d = ev.check_tool("send_email", [("hort", hort_rule), ("llming", inner_rule)])
        assert not d.allowed

    def test_sap_taint_blocks_shell(self, world: WorldConfig) -> None:
        """After reading SAP data, shell should be blocked."""
        ev = WireEvaluator(groups=world.groups)
        shell_rule, _ = get_llming_connection(world.hort, "openhort/shell")
        d = ev.check_tool(
            "read_output",
            [("llming", shell_rule)],
            current_taint={"source:sap"},
        )
        assert not d.allowed
        assert "Tainted data blocked" in d.reason

    def test_sap_taint_blocks_o365(self, world: WorldConfig) -> None:
        """SAP data cannot enter the O365 hull."""
        ev = WireEvaluator(groups=world.groups)
        hort_rule, _ = get_llming_connection(world.hort, "hort/o365")
        d = ev.check_tool(
            "read_email",
            [("hort", hort_rule)],
            current_taint={"source:sap"},
        )
        assert not d.allowed

    def test_clean_taint_allows_shell(self, world: WorldConfig) -> None:
        """Without SAP/O365 taint, shell works fine."""
        ev = WireEvaluator(groups=world.groups)
        shell_rule, _ = get_llming_connection(world.hort, "openhort/shell")
        d = ev.check_tool("read_output", [("llming", shell_rule)])
        assert d.allowed


class TestScenarioFencesWithGroups:
    """Scenario: Overlapping fences with custom groups."""

    @pytest.fixture()
    def world(self) -> WorldConfig:
        return parse_world_config({
            "groups": {
                "code-safe": {
                    "include_groups": ["read"],
                    "add": ["create_pr", "push"],
                },
            },
            "hort": {
                "name": "Dev Setup",
                "llmings": [
                    {"openhort/telegram": {}},
                    {"openhort/github": {}},
                    {"openhort/shell": {}},
                    {"sap/connector": {}},
                ],
                "fences": [
                    {
                        "name": "dev-tools",
                        "members": ["openhort/telegram", "openhort/github", "openhort/shell"],
                        "inside": {"allow_groups": ["read", "write", "code-safe"]},
                        "boundary": {"deny_groups": ["send", "destroy"]},
                    },
                    {
                        "name": "sensitive",
                        "members": ["sap/connector"],
                        "inside": {"allow_groups": ["read"]},
                        "boundary": {
                            "taint": "source:sensitive",
                            "block_taint": ["source:sensitive"],
                            "deny_groups": ["send"],
                        },
                    },
                ],
            },
        })

    def test_inside_dev_fence_allows_write(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        d = ev.check_tool(
            "create_pr", [],
            fences=world.hort.fences,
            source_llming="openhort/telegram",
            target_llming="openhort/github",
        )
        assert d.allowed

    def test_dev_to_sap_boundary_blocks_send(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        d = ev.check_tool(
            "send_report", [],
            fences=world.hort.fences,
            source_llming="openhort/telegram",
            target_llming="sap/connector",
        )
        # sensitive fence boundary denies send
        assert not d.allowed

    def test_sap_boundary_adds_taint(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        d = ev.check_tool(
            "get_balance", [],
            fences=world.hort.fences,
            source_llming="openhort/telegram",
            target_llming="sap/connector",
        )
        assert d.allowed
        assert "source:sensitive" in d.taint_labels

    def test_sensitive_taint_blocked_at_boundary(self, world: WorldConfig) -> None:
        """Once tainted, data can't cross the sensitive fence boundary."""
        ev = WireEvaluator(groups=world.groups)
        d = ev.check_tool(
            "get_balance", [],
            fences=world.hort.fences,
            source_llming="openhort/shell",
            target_llming="sap/connector",
            current_taint={"source:sensitive"},
        )
        assert not d.allowed


class TestScenarioCompleteRealWorld:
    """Scenario: Full real-world config with all features."""

    @pytest.fixture()
    def world(self) -> WorldConfig:
        return parse_world_config({
            "groups": {
                "read-only": {"auto": ["read_*", "get_*", "list_*", "search_*"], "color": "green"},
                "standard": {"include_groups": ["read-only"], "auto": ["create_*", "update_*"], "color": "yellow"},
                "outbound": {"auto": ["send_*", "post_*", "push_*"], "color": "orange"},
                "destructive": {"auto": ["delete_*", "drop_*"], "color": "red"},
                "code-safe": {"include_groups": ["read-only"], "add": ["create_pr", "push"]},
            },
            "hort": {
                "name": "My Desktop",
                "agent": {"provider": "claude-code", "model": "claude-sonnet-4-6"},
                "container": {"memory": "4g", "cpus": 4, "network": ["api.anthropic.com"]},
                "llmings": [
                    {"openhort/telegram": {"token": "env:TG_TOKEN", "allowed_users": ["michael"]}},
                    {"openhort/github": {"allow_groups": ["code-safe"], "deny_groups": ["destructive"]}},
                    {"openhort/shell": {
                        "allow_groups": ["read-only"],
                        "block_taint": ["source:o365", "source:sap", "source:hr"],
                    }},
                    {"hort/o365": {"taint": "source:o365", "block_taint": ["source:sap"]}},
                    {"hort/sap": {"taint": "source:sap", "block_taint": ["source:o365"]}},
                    {"hort/hr": {"taint": ["source:hr", "content:pii"], "block_taint": ["source:o365", "source:sap"]}},
                ],
                "fences": [
                    {
                        "name": "external-data",
                        "members": ["hort/o365", "hort/sap", "hort/hr"],
                        "inside": {"allow_groups": ["read-only"]},
                        "boundary": {"deny_groups": ["outbound", "destructive"]},
                    },
                ],
                "direct": [
                    {"between": ["openhort/telegram", "microsoft/office365"], "allow": ["email_arrived"]},
                ],
                "circuits": [
                    {"on": "microsoft/office365::email_arrived", "filter": {"from": "*@company.com"}},
                ],
            },
            "hort/o365": {
                "name": "O365",
                "container": {"network": ["graph.microsoft.com"]},
                "credentials": {"AZURE_CLIENT_ID": "env:AZURE_CLIENT_ID"},
                "llmings": [
                    {"microsoft/office365": {"allow_groups": ["read-only"], "deny_groups": ["outbound", "destructive"]}},
                ],
            },
            "hort/sap": {
                "name": "SAP",
                "container": {"network": ["sap.internal:8443"]},
                "credentials": {"SAP_USER": "env:SAP_USER", "SAP_PASS": "vault:sap/password"},
                "llmings": [
                    {"sap/connector": {"allow_groups": ["read-only"]}},
                ],
            },
            "hort/hr": {
                "name": "HR Database",
                "container": {"network": ["postgres.internal:5432"]},
                "credentials": {"PG_URI": "vault:hr/connection-string"},
                "llmings": [
                    {"openhort/postgres": {"allow_groups": ["read-only"]}},
                ],
            },
        })

    def test_structure(self, world: WorldConfig) -> None:
        assert world.hort.name == "My Desktop"
        assert len(world.sub_horts) == 3
        assert "hort/o365" in world.sub_horts
        assert "hort/sap" in world.sub_horts
        assert "hort/hr" in world.sub_horts

    def test_github_code_safe(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/github")
        assert ev.check_tool("read_file", [("w", ruleset)]).allowed
        assert ev.check_tool("create_pr", [("w", ruleset)]).allowed
        assert ev.check_tool("push", [("w", ruleset)]).allowed
        assert not ev.check_tool("delete_repo", [("w", ruleset)]).allowed

    def test_shell_clean_ok(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/shell")
        assert ev.check_tool("read_output", [("w", ruleset)]).allowed

    def test_shell_tainted_blocked(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        ruleset, _ = get_llming_connection(world.hort, "openhort/shell")
        for taint in ["source:o365", "source:sap", "source:hr"]:
            d = ev.check_tool("read_output", [("w", ruleset)], current_taint={taint})
            assert not d.allowed, f"Should block with taint {taint}"

    def test_o365_read_tainted(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        hort_r, _ = get_llming_connection(world.hort, "hort/o365")
        inner_r, _ = get_llming_connection(world.sub_horts["hort/o365"], "microsoft/office365")
        d = ev.check_tool("read_email", [("hort", hort_r), ("llming", inner_r)])
        assert d.allowed
        assert "source:o365" in d.taint_labels

    def test_cross_contamination_blocked(self, world: WorldConfig) -> None:
        """SAP taint cannot enter O365 hull."""
        ev = WireEvaluator(groups=world.groups)
        hort_r, _ = get_llming_connection(world.hort, "hort/o365")
        d = ev.check_tool("read_email", [("hort", hort_r)], current_taint={"source:sap"})
        assert not d.allowed

    def test_fence_blocks_outbound_from_sensitive(self, world: WorldConfig) -> None:
        """External-data fence blocks send from any sensitive source."""
        ev = WireEvaluator(groups=world.groups)
        d = ev.check_tool(
            "send_report", [],
            fences=world.hort.fences,
            source_llming="hort/sap",
            target_llming="openhort/telegram",
        )
        assert not d.allowed

    def test_credentials_reference(self, world: WorldConfig) -> None:
        sap = world.sub_horts["hort/sap"]
        assert sap.credentials["SAP_USER"] == "env:SAP_USER"
        assert sap.credentials["SAP_PASS"] == "vault:sap/password"

    def test_direct_connection(self, world: WorldConfig) -> None:
        assert len(world.hort.direct) == 1
        d = world.hort.direct[0]
        assert d.between == ["openhort/telegram", "microsoft/office365"]
        assert d.rules.allow == ["email_arrived"]


class TestScenarioDockerContainerLimits:
    """Scenario: Multiple containers with different resource limits."""

    @pytest.fixture()
    def world(self) -> WorldConfig:
        return parse_world_config({
            "hort": {
                "name": "Multi-Container",
                "agent": {"provider": "claude-code"},
                "container": {"memory": "4g", "cpus": 4, "network": ["api.anthropic.com"]},
                "llmings": [
                    {"openhort/telegram": {}},
                    {"hort/trusted-worker": {}},
                    {"hort/untrusted-sandbox": {"deny_groups": ["send", "destroy"]}},
                ],
            },
            "hort/trusted-worker": {
                "name": "Trusted Worker",
                "agent": {"provider": "claude-code", "model": "claude-sonnet-4-6"},
                "container": {"memory": "8g", "cpus": 8, "network": ["api.anthropic.com", "github.com"]},
                "llmings": [
                    {"openhort/github": {"allow_groups": ["read", "write"]}},
                    {"openhort/shell": {}},
                ],
            },
            "hort/untrusted-sandbox": {
                "name": "Untrusted Sandbox",
                "agent": {"provider": "claude-code", "model": "claude-haiku"},
                "container": {"memory": "1g", "cpus": 1, "network": []},
                "llmings": [
                    {"openhort/shell": {"allow_groups": ["read"]}},
                ],
            },
        })

    def test_trusted_has_resources(self, world: WorldConfig) -> None:
        trusted = world.sub_horts["hort/trusted-worker"]
        assert trusted.container is not None
        assert trusted.container.memory == "8g"
        assert trusted.container.cpus == 8
        assert "github.com" in trusted.container.network

    def test_untrusted_minimal_resources(self, world: WorldConfig) -> None:
        untrusted = world.sub_horts["hort/untrusted-sandbox"]
        assert untrusted.container is not None
        assert untrusted.container.memory == "1g"
        assert untrusted.container.cpus == 1
        assert untrusted.container.network == []

    def test_untrusted_send_blocked_by_parent(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        parent_rule, _ = get_llming_connection(world.hort, "hort/untrusted-sandbox")
        d = ev.check_tool("send_data", [("hort", parent_rule)])
        assert not d.allowed

    def test_untrusted_read_allowed(self, world: WorldConfig) -> None:
        ev = WireEvaluator(groups=world.groups)
        parent_rule, _ = get_llming_connection(world.hort, "hort/untrusted-sandbox")
        inner_rule, _ = get_llming_connection(
            world.sub_horts["hort/untrusted-sandbox"], "openhort/shell",
        )
        d = ev.check_tool("read_output", [("hort", parent_rule), ("llming", inner_rule)])
        assert d.allowed


class TestScenarioFileBasedConfig:
    """Test loading from an actual YAML file."""

    def test_load_from_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "openhort.yaml"
        config_file.write_text(textwrap.dedent("""\
            hort:
              name: "File-Based Test"
              agent:
                provider: claude-code
              llmings:
                - openhort/telegram:
                    token: env:TEST_TOKEN
                - openhort/shell:
                    allow_groups: [read]
                    deny_groups: [destroy]
              fences:
                - name: safe-zone
                  members: [openhort/telegram, openhort/shell]
                  inside:
                    allow_groups: [read, write]
        """))

        world = load_world_config(config_file)
        assert world.hort.name == "File-Based Test"
        assert world.hort.agent is not None
        assert world.hort.agent.provider == "claude-code"
        assert len(world.hort.fences) == 1
        assert world.hort.fences[0].name == "safe-zone"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_world_config("/nonexistent/openhort.yaml")


# ── Per-Message Taint ─────────────────────────────────────────────


class TestTaintedMessage:
    """Test per-message taint and redaction."""

    def test_clean_message_not_redacted(self) -> None:
        msg = TaintedMessage(role="assistant", content="Hello")
        redacted = msg.redact_for({"source:sap"})
        assert redacted.content == "Hello"

    def test_tainted_message_redacted(self) -> None:
        msg = TaintedMessage(
            role="assistant",
            content="Balance: $12,345",
            taint_labels=frozenset({"source:sap", "content:financial"}),
        )
        redacted = msg.redact_for({"source:sap"})
        assert redacted.content == "[Hidden: confidential content]"

    def test_no_block_taint_no_redaction(self) -> None:
        msg = TaintedMessage(
            role="assistant",
            content="Secret data",
            taint_labels=frozenset({"source:sap"}),
        )
        redacted = msg.redact_for(set())
        assert redacted.content == "Secret data"

    def test_non_matching_taint_not_redacted(self) -> None:
        msg = TaintedMessage(
            role="assistant",
            content="Weather is sunny",
            taint_labels=frozenset({"source:weather"}),
        )
        redacted = msg.redact_for({"source:sap"})
        assert redacted.content == "Weather is sunny"


class TestConversationTaint:
    """Test conversation-level taint tracking with per-message labels."""

    def test_zone_taint_is_union(self) -> None:
        conv = ConversationTaint()
        conv.add_message("user", "check SAP", frozenset({"source:sap"}))
        conv.add_message("user", "check O365", frozenset({"source:o365"}))
        assert conv.zone_taint == {"source:sap", "source:o365"}

    def test_visible_history_redacts_tainted(self) -> None:
        conv = ConversationTaint()
        conv.add_message("user", "What's my balance?")
        conv.add_message("assistant", "Your balance is $12,345",
                         frozenset({"source:sap", "content:financial"}),
                         tool_name="sap.get_balance")
        conv.add_message("user", "Write a birthday email for Bob")

        # When composing email (blocks sap taint), LLM sees:
        visible = conv.visible_history(blocked_taint={"source:sap"})
        assert len(visible) == 3
        assert visible[0].content == "What's my balance?"          # clean → shown
        assert visible[1].content == "[Hidden: confidential content]"  # tainted → redacted
        assert visible[2].content == "Write a birthday email for Bob"  # clean → shown

    def test_visible_history_no_block_shows_all(self) -> None:
        conv = ConversationTaint()
        conv.add_message("assistant", "Secret", frozenset({"source:sap"}))
        visible = conv.visible_history(blocked_taint=None)
        assert visible[0].content == "Secret"

    def test_empty_conversation(self) -> None:
        conv = ConversationTaint()
        assert conv.zone_taint == set()
        assert conv.visible_history() == []


# ── E2E: Telegram Financial Data + Birthday Email ─────────────────


class TestScenarioTelegramMixedChat:
    """E2E scenario: user asks about financial data, then sends a birthday email.

    The financial data is tainted. The birthday email tool blocks that
    taint.  The LLM should see the financial response as redacted when
    composing the email, but the tool call itself should be allowed
    because the email content is clean.

    Flow:
    1. User: "What's my SAP balance?"
    2. Agent calls sap.get_balance → tainted {source:sap, content:financial}
    3. Agent responds: "Your balance is $12,345"
    4. User: "Write a happy birthday email to Bob"
    5. Agent calls email.send_email → target has block_taint: [source:sap]
    6. System checks: is the EMAIL CONTENT tainted? No — it's about birthdays.
    7. System redacts SAP messages from LLM's view so it can't leak them.
    8. Email sends successfully. Financial data never leaves.
    """

    @pytest.fixture()
    def world(self) -> WorldConfig:
        return parse_world_config({
            "hort": {
                "name": "Mixed Chat Test",
                "agent": {"provider": "claude-code"},
                "llmings": [
                    {"openhort/telegram": {}},
                    {"hort/sap": {"taint": "source:sap", "block_taint": ["source:o365"]}},
                    {"openhort/email": {
                        "allow_groups": ["read", "send"],
                        "block_taint": ["source:sap", "content:financial"],
                    }},
                ],
            },
            "hort/sap": {
                "container": {"network": ["sap.internal:8443"]},
                "llmings": [
                    {"sap/connector": {"allow_groups": ["read"]}},
                ],
            },
        })

    def test_step1_sap_read_allowed(self, world: WorldConfig) -> None:
        """Step 1-2: User asks about SAP balance, tool call allowed."""
        ev = WireEvaluator(groups=world.groups)
        hort_rule, _ = get_llming_connection(world.hort, "hort/sap")
        inner_rule, _ = get_llming_connection(
            world.sub_horts["hort/sap"], "sap/connector",
        )
        d = ev.check_tool("get_balance", [("hort", hort_rule), ("llming", inner_rule)])
        assert d.allowed
        assert "source:sap" in d.taint_labels

    def test_step2_conversation_tracks_taint(self, world: WorldConfig) -> None:
        """Step 3: After SAP response, conversation has taint."""
        conv = ConversationTaint()
        conv.add_message("user", "What's my SAP balance?")
        conv.add_message(
            "assistant", "Your balance is $12,345",
            frozenset({"source:sap", "content:financial"}),
            tool_name="sap.get_balance",
        )
        assert "source:sap" in conv.zone_taint
        assert "content:financial" in conv.zone_taint

    def test_step3_email_tool_allowed_despite_zone_taint(self, world: WorldConfig) -> None:
        """Step 4-5: Birthday email tool is allowed.

        The EMAIL tool itself is allowed because the email content
        is about birthdays, not financial data.  The block_taint on
        the email wire means tainted MESSAGES are redacted from the
        LLM's view — NOT that the tool is blocked entirely.
        """
        ev = WireEvaluator(groups=world.groups)
        email_rule, _ = get_llming_connection(world.hort, "openhort/email")
        # The tool call itself is allowed (send_email is in "send" group,
        # which is in allow_groups)
        d = ev.check_tool("send_email", [("llming", email_rule)])
        assert d.allowed

    def test_step4_email_with_sap_taint_blocks(self, world: WorldConfig) -> None:
        """If the conversation HAS sap taint and the email wire blocks it,
        then calling email with zone-level taint check would block."""
        ev = WireEvaluator(groups=world.groups)
        email_rule, _ = get_llming_connection(world.hort, "openhort/email")
        # With zone-level taint check (old behavior) — blocks
        d = ev.check_tool(
            "send_email", [("llming", email_rule)],
            current_taint={"source:sap"},
        )
        assert not d.allowed
        assert "Tainted data blocked" in d.reason

    def test_step5_redacted_history_for_email(self, world: WorldConfig) -> None:
        """Step 6-7: When composing email, LLM sees redacted history.

        The financial data is hidden. The birthday request is visible.
        The LLM composes the email from clean context only.
        """
        conv = ConversationTaint()

        # Turn 1: SAP query
        conv.add_message("user", "What's my SAP balance?")
        conv.add_message(
            "assistant", "Your balance is $12,345",
            frozenset({"source:sap", "content:financial"}),
            tool_name="sap.get_balance",
        )

        # Turn 2: Birthday email (clean)
        conv.add_message("user", "Write a happy birthday email to Bob")

        # Get the email wire's block_taint
        email_rule, _ = get_llming_connection(world.hort, "openhort/email")
        blocked = set(email_rule.block_taint or [])

        # Prepare history for the email tool
        ev = WireEvaluator(groups=world.groups)
        visible = ev.prepare_history_for_tool(conv, email_rule)

        # User's SAP question: clean, shown as-is
        assert visible[0].content == "What's my SAP balance?"
        # SAP response: tainted, REDACTED
        assert visible[1].content == "[Hidden: confidential content]"
        # Birthday request: clean, shown as-is
        assert visible[2].content == "Write a happy birthday email to Bob"

    def test_step6_full_e2e_flow(self, world: WorldConfig) -> None:
        """Complete flow: SAP read → email compose → email allowed.

        Simulates the entire conversation lifecycle:
        1. User asks about SAP → allowed, taint recorded
        2. User asks for birthday email → tool allowed
        3. LLM sees redacted history → composes from clean data
        4. Email sends without financial data
        """
        ev = WireEvaluator(groups=world.groups)
        conv = ConversationTaint()

        # ── Turn 1: SAP read ──────────────────────────────────────
        hort_rule, _ = get_llming_connection(world.hort, "hort/sap")
        inner_rule, _ = get_llming_connection(
            world.sub_horts["hort/sap"], "sap/connector",
        )
        sap_decision = ev.check_tool(
            "get_balance", [("hort", hort_rule), ("llming", inner_rule)],
        )
        assert sap_decision.allowed

        # Record the conversation
        conv.add_message("user", "What's my SAP balance?")
        conv.add_message(
            "assistant", "Your balance is $12,345",
            frozenset(set(sap_decision.taint_labels)),
            tool_name="sap.get_balance",
        )

        # ── Turn 2: Birthday email ────────────────────────────────
        conv.add_message("user", "Write a happy birthday email to Bob")

        # Check: can we use the email tool?
        email_rule, _ = get_llming_connection(world.hort, "openhort/email")

        # With per-message approach: prepare redacted history
        visible = ev.prepare_history_for_tool(conv, email_rule)

        # LLM sees clean history for email composition
        assert visible[0].content == "What's my SAP balance?"
        assert visible[1].content == "[Hidden: confidential content]"
        assert visible[2].content == "Write a happy birthday email to Bob"

        # The email tool call itself is allowed (no taint on THIS call)
        email_decision = ev.check_tool("send_email", [("llming", email_rule)])
        assert email_decision.allowed

        # Record the email
        conv.add_message(
            "assistant", "Happy birthday Bob! Wishing you a great year ahead.",
            frozenset(),  # clean — no taint
            tool_name="email.send_email",
        )

        # ── Verify final state ────────────────────────────────────
        # Zone taint still has SAP (it never goes away)
        assert "source:sap" in conv.zone_taint
        # But the email message itself is clean
        assert conv.messages[-1].taint_labels == frozenset()
        # User sees everything (no redaction)
        full_history = conv.visible_history(blocked_taint=None)
        assert full_history[1].content == "Your balance is $12,345"
        assert full_history[3].content == "Happy birthday Bob! Wishing you a great year ahead."

    def test_user_always_sees_everything(self, world: WorldConfig) -> None:
        """The user's view is never redacted — only the LLM's view."""
        conv = ConversationTaint()
        conv.add_message("assistant", "Secret: $12,345",
                         frozenset({"source:sap"}))
        conv.add_message("assistant", "Weather: sunny")

        # User view: everything
        user_view = conv.visible_history(blocked_taint=None)
        assert user_view[0].content == "Secret: $12,345"
        assert user_view[1].content == "Weather: sunny"

        # LLM view for email tool: SAP redacted
        llm_view = conv.visible_history(blocked_taint={"source:sap"})
        assert llm_view[0].content == "[Hidden: confidential content]"
        assert llm_view[1].content == "Weather: sunny"
