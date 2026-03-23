"""Configuration loader for the Telegram bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class HortConfig:
    url: str = "http://localhost:8940"


@dataclass(frozen=True)
class BotConfig:
    allowed_users: list[str] = field(default_factory=list)
    hort: HortConfig = field(default_factory=HortConfig)
    token: str = ""

    def is_user_allowed(self, username: str | None) -> bool:
        """Check if a Telegram username is in the allow list."""
        if not self.allowed_users:
            return False  # empty list = nobody allowed
        if username is None:
            return False
        # Strip leading @ if present
        clean = username.lstrip("@")
        return clean in self.allowed_users


def load_config(path: str | Path | None = None) -> BotConfig:
    """Load bot config from YAML file + environment."""
    if path is None:
        path = Path(__file__).parent / "bot_config.yaml"
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Bot config not found: {path}\n"
            "Create bot_config.yaml with at least:\n"
            "  telegram:\n"
            "    allowed_users:\n"
            "      - your_telegram_username"
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    tg = raw.get("telegram", {})
    hort_raw = raw.get("hort", {})

    allowed = tg.get("allowed_users", [])
    if not allowed:
        raise ValueError(
            "bot_config.yaml must specify at least one allowed_users entry. "
            "An empty allow list means nobody can use the bot."
        )

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    return BotConfig(
        allowed_users=allowed,
        hort=HortConfig(url=hort_raw.get("url", "http://localhost:8940")),
        token=token,
    )
