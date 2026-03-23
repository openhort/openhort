"""Tests for config loading and user ACL."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
import yaml

from subprojects.telegram_bot.config import BotConfig, HortConfig, load_config


class TestBotConfig:
    def test_allowed_user(self) -> None:
        cfg = BotConfig(allowed_users=["alice_dev"])
        assert cfg.is_user_allowed("alice_dev") is True

    def test_allowed_user_with_at_prefix(self) -> None:
        cfg = BotConfig(allowed_users=["alice_dev"])
        assert cfg.is_user_allowed("@alice_dev") is True

    def test_rejected_user(self) -> None:
        cfg = BotConfig(allowed_users=["alice_dev"])
        assert cfg.is_user_allowed("random_person") is False

    def test_none_username_rejected(self) -> None:
        cfg = BotConfig(allowed_users=["alice_dev"])
        assert cfg.is_user_allowed(None) is False

    def test_empty_allow_list_rejects_all(self) -> None:
        cfg = BotConfig(allowed_users=[])
        assert cfg.is_user_allowed("alice_dev") is False

    def test_multiple_users(self) -> None:
        cfg = BotConfig(allowed_users=["alice", "bob", "alice_dev"])
        assert cfg.is_user_allowed("alice") is True
        assert cfg.is_user_allowed("bob") is True
        assert cfg.is_user_allowed("alice_dev") is True
        assert cfg.is_user_allowed("eve") is False

    def test_case_sensitive(self) -> None:
        cfg = BotConfig(allowed_users=["alice_dev"])
        assert cfg.is_user_allowed("Alice_Dev") is False


class TestLoadConfig:
    def test_load_valid_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "bot_config.yaml"
        cfg_file.write_text(
            yaml.dump(
                {
                    "telegram": {"allowed_users": ["alice_dev"]},
                    "hort": {"url": "http://localhost:9999"},
                }
            )
        )
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
        try:
            cfg = load_config(cfg_file)
            assert cfg.allowed_users == ["alice_dev"]
            assert cfg.hort.url == "http://localhost:9999"
            assert cfg.token == "test-token"
        finally:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Bot config not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_empty_allowed_users_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "bot_config.yaml"
        cfg_file.write_text(yaml.dump({"telegram": {"allowed_users": []}}))
        with pytest.raises(ValueError, match="must specify at least one"):
            load_config(cfg_file)

    def test_no_telegram_section_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "bot_config.yaml"
        cfg_file.write_text(yaml.dump({"hort": {"url": "http://x"}}))
        with pytest.raises(ValueError, match="must specify at least one"):
            load_config(cfg_file)

    def test_defaults(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "bot_config.yaml"
        cfg_file.write_text(
            yaml.dump({"telegram": {"allowed_users": ["testuser"]}})
        )
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        cfg = load_config(cfg_file)
        assert cfg.hort.url == "http://localhost:8940"
        assert cfg.token == ""
