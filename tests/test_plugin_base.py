"""Tests for PluginBase, PluginContext, and PluginConfig."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from hort.ext.file_store import LocalFileStore
from hort.ext.plugin import PluginBase, PluginConfig, PluginContext
from hort.ext.scheduler import PluginScheduler
from hort.ext.store import FilePluginStore


@pytest.fixture
def context(tmp_path: Path) -> PluginContext:
    return PluginContext(
        plugin_id="test-plugin",
        store=FilePluginStore("test-plugin", base_dir=tmp_path),
        files=LocalFileStore("test-plugin", base_dir=tmp_path),
        config=PluginConfig(
            plugin_id="test-plugin",
            _raw={"setting1": "value1"},
            _feature_defaults={"alerts": True, "logging": False},
        ),
        scheduler=PluginScheduler("test-plugin"),
        logger=logging.getLogger("hort.plugin.test-plugin"),
    )


class TestPluginConfig:
    def test_get(self) -> None:
        cfg = PluginConfig("p", _raw={"key": "val"})
        assert cfg.get("key") == "val"
        assert cfg.get("missing", 42) == 42

    def test_set(self) -> None:
        cfg = PluginConfig("p")
        cfg.set("key", "val")
        assert cfg.get("key") == "val"

    def test_raw(self) -> None:
        cfg = PluginConfig("p", _raw={"a": 1, "b": 2})
        assert cfg.raw == {"a": 1, "b": 2}

    def test_feature_defaults(self) -> None:
        cfg = PluginConfig(
            "p", _feature_defaults={"alerts": True, "logging": False}
        )
        assert cfg.is_feature_enabled("alerts") is True
        assert cfg.is_feature_enabled("logging") is False
        assert cfg.is_feature_enabled("unknown") is True  # default True

    def test_feature_override(self) -> None:
        cfg = PluginConfig(
            "p", _feature_defaults={"alerts": True, "logging": False}
        )
        cfg.set_feature("logging", True)
        assert cfg.is_feature_enabled("logging") is True
        cfg.set_feature("alerts", False)
        assert cfg.is_feature_enabled("alerts") is False

    def test_feature_override_from_raw(self) -> None:
        cfg = PluginConfig(
            "p",
            _raw={"_feature_overrides": {"alerts": False}},
            _feature_defaults={"alerts": True},
        )
        assert cfg.is_feature_enabled("alerts") is False


class TestPluginBase:
    def test_properties(self, context: PluginContext) -> None:
        class MyPlugin(PluginBase):
            pass

        plugin = MyPlugin()
        plugin._ctx = context

        assert plugin.plugin_id == "test-plugin"
        assert isinstance(plugin.store, FilePluginStore)
        assert isinstance(plugin.files, LocalFileStore)
        assert isinstance(plugin.config, PluginConfig)
        assert plugin.log.name == "hort.plugin.test-plugin"
        assert plugin.shared_stores == {}

    def test_config_access(self, context: PluginContext) -> None:
        class MyPlugin(PluginBase):
            pass

        plugin = MyPlugin()
        plugin._ctx = context

        assert plugin.config.get("setting1") == "value1"
        assert plugin.config.is_feature_enabled("alerts") is True
        assert plugin.config.is_feature_enabled("logging") is False

    def test_shared_stores(self, tmp_path: Path) -> None:
        shared = FilePluginStore("other-plugin", base_dir=tmp_path)
        ctx = PluginContext(
            plugin_id="test",
            store=FilePluginStore("test", base_dir=tmp_path),
            files=LocalFileStore("test", base_dir=tmp_path),
            config=PluginConfig("test"),
            scheduler=PluginScheduler("test"),
            logger=logging.getLogger("test"),
            shared_stores={"other-plugin": shared},
        )

        class MyPlugin(PluginBase):
            pass

        plugin = MyPlugin()
        plugin._ctx = ctx
        assert "other-plugin" in plugin.shared_stores

    def test_activate_deactivate(self, context: PluginContext) -> None:
        activated = {"yes": False}

        class MyPlugin(PluginBase):
            def activate(self, config: dict[str, Any]) -> None:
                activated["yes"] = True

            def deactivate(self) -> None:
                activated["yes"] = False

        plugin = MyPlugin()
        plugin._ctx = context
        plugin.activate({"x": 1})
        assert activated["yes"] is True
        plugin.deactivate()
        assert activated["yes"] is False
