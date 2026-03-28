"""Tests for the Hort Map config system."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hort.hortmap.models import (
    BLOCK_CATALOG,
    BlockTypeDef,
    ConnectionDef,
    ExportDef,
    HortConfig,
    LlmingComponentDef,
    McpComponentDef,
    NotifierComponentDef,
    SubHortDef,
    WatcherComponentDef,
)
from hort.hortmap.store import delete_config, list_configs, load_config, save_config


# ── Model tests ─────────────────────────────────────────────────────


class TestModels:
    def test_mcp_component(self) -> None:
        c = McpComponentDef(component_id="fs", command="npx mcp-fs /tmp")
        assert c.component_type == "mcp"
        assert c.transport == "stdio"

    def test_llming_component(self) -> None:
        c = LlmingComponentDef(component_id="claude", provider="claude-code", model="sonnet")
        assert c.component_type == "llming"
        assert c.budget_usd == 1.0

    def test_watcher_component(self) -> None:
        c = WatcherComponentDef(component_id="screen1", app_filter="iTerm")
        assert c.component_type == "watcher"
        assert c.region == "full"

    def test_notifier_component(self) -> None:
        c = NotifierComponentDef(component_id="tg", channel="telegram")
        assert c.component_type == "notifier"
        assert c.on_event == "both"

    def test_connection(self) -> None:
        c = ConnectionDef(source_id="screen1", target_id="tg")
        assert c.source_id == "screen1"

    def test_sub_hort(self) -> None:
        sh = SubHortDef(
            hort_id="sandbox1",
            label="Research Sandbox",
            memory="512m",
            components=[
                LlmingComponentDef(component_id="agent1", provider="claude-code"),
            ],
        )
        assert len(sh.components) == 1
        assert sh.network == "restricted"

    def test_hort_config_full(self) -> None:
        cfg = HortConfig(
            hort_id="mac-studio",
            name="My Mac",
            node_id="mac-studio",
            components=[
                WatcherComponentDef(component_id="w1", app_filter="iTerm"),
                NotifierComponentDef(component_id="n1", channel="telegram"),
            ],
            connections=[ConnectionDef(source_id="w1", target_id="n1")],
            sub_horts=[
                SubHortDef(hort_id="sb1", label="Sandbox"),
            ],
            exports=[ExportDef(component_id="w1", to=["*"])],
        )
        assert cfg.name == "My Mac"
        assert len(cfg.components) == 2
        assert len(cfg.connections) == 1
        assert len(cfg.sub_horts) == 1
        assert len(cfg.exports) == 1

    def test_hort_config_json_roundtrip(self) -> None:
        cfg = HortConfig(
            hort_id="test",
            name="Test",
            components=[McpComponentDef(component_id="mcp1", command="echo")],
        )
        j = cfg.model_dump_json()
        cfg2 = HortConfig.model_validate_json(j)
        assert cfg2.hort_id == "test"
        assert len(cfg2.components) == 1

    def test_extra_fields_accepted(self) -> None:
        cfg = HortConfig(hort_id="x", future_field="yes")  # type: ignore[call-arg]
        assert cfg.future_field == "yes"  # type: ignore[attr-defined]

    def test_catalog_has_all_types(self) -> None:
        types = {b.block_type for b in BLOCK_CATALOG}
        assert types >= {"mcp", "llming", "watcher", "notifier", "sub_hort"}

    def test_catalog_fields(self) -> None:
        for bt in BLOCK_CATALOG:
            assert bt.label
            assert bt.icon
            assert bt.color


# ── Store tests ─────────────────────────────────────────────────────


class TestStore:
    @pytest.fixture(autouse=True)
    def _tmpdir(self, tmp_path: Path):
        with patch("hort.hortmap.store._HORTMAP_DIR", tmp_path):
            yield tmp_path

    def test_save_and_load(self) -> None:
        cfg = HortConfig(hort_id="h1", name="Test Hort")
        save_config(cfg)
        loaded = load_config("h1")
        assert loaded is not None
        assert loaded.name == "Test Hort"

    def test_load_missing(self) -> None:
        assert load_config("nonexistent") is None

    def test_list_configs(self) -> None:
        save_config(HortConfig(hort_id="a", name="A"))
        save_config(HortConfig(hort_id="b", name="B"))
        result = list_configs()
        assert len(result) == 2

    def test_delete_config(self) -> None:
        save_config(HortConfig(hort_id="del", name="Delete Me"))
        assert delete_config("del") is True
        assert load_config("del") is None

    def test_delete_missing(self) -> None:
        assert delete_config("nope") is False

    def test_save_with_components(self) -> None:
        cfg = HortConfig(
            hort_id="full",
            name="Full",
            components=[
                WatcherComponentDef(component_id="w", app_filter="Chrome"),
                NotifierComponentDef(component_id="n"),
            ],
            connections=[ConnectionDef(source_id="w", target_id="n")],
        )
        save_config(cfg)
        loaded = load_config("full")
        assert loaded is not None
        assert len(loaded.components) == 2
        assert len(loaded.connections) == 1
