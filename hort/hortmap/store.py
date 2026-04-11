"""Hort map persistence — save/load hort configs as JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from hort.hortmap.models import HortConfig

logger = logging.getLogger("hort.hortmap.store")

def _hortmap_dir() -> Path:
    from hort.hort_config import hort_data_dir
    return hort_data_dir() / "hortmap"

_HORTMAP_DIR = _hortmap_dir()


def _ensure_dir() -> None:
    _HORTMAP_DIR.mkdir(parents=True, exist_ok=True)


def save_config(config: HortConfig) -> None:
    """Save a hort config to disk."""
    _ensure_dir()
    path = _HORTMAP_DIR / f"{config.hort_id}.json"
    path.write_text(config.model_dump_json(indent=2))


def load_config(hort_id: str) -> HortConfig | None:
    """Load a hort config by ID."""
    path = _HORTMAP_DIR / f"{hort_id}.json"
    if not path.exists():
        return None
    try:
        return HortConfig.model_validate_json(path.read_text())
    except Exception:
        logger.exception("Failed to load hort config %s", hort_id)
        return None


def list_configs() -> list[HortConfig]:
    """List all saved hort configs."""
    _ensure_dir()
    configs = []
    for path in sorted(_HORTMAP_DIR.glob("*.json")):
        try:
            configs.append(HortConfig.model_validate_json(path.read_text()))
        except Exception:
            logger.warning("Skipping invalid config: %s", path)
    return configs


def delete_config(hort_id: str) -> bool:
    """Delete a hort config."""
    path = _HORTMAP_DIR / f"{hort_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
