"""Hort instance paths — single source of truth for all directory locations.

Each hort instance gets its own data directory. Multiple instances on
the same machine use different directories. Configured via:

1. ``HORT_DATA_DIR`` environment variable
2. ``data_dir`` in ``hort-config.yaml``
3. Default: ``~/.hort/{instance_name}/``

The instance name comes from ``hort-config.yaml`` (``name`` field)
or defaults to ``"default"``.
"""

from __future__ import annotations

import os
from pathlib import Path

_resolved: Path | None = None


def get_data_dir() -> Path:
    """Get the data directory for this hort instance.

    Resolution order:
    1. HORT_DATA_DIR env var (absolute path)
    2. hort-config.yaml ``data_dir`` field
    3. ~/.hort/{instance_name}/

    Cached after first call.
    """
    global _resolved
    if _resolved is not None:
        return _resolved

    # 1. Environment variable (highest priority)
    env = os.environ.get("HORT_DATA_DIR", "")
    if env:
        _resolved = Path(env)
        _resolved.mkdir(parents=True, exist_ok=True)
        return _resolved

    # 2. Config file
    try:
        from hort.hort_config import get_hort_config
        cfg = get_hort_config()
        if hasattr(cfg, "data_dir") and cfg.data_dir:
            _resolved = Path(cfg.data_dir)
            _resolved.mkdir(parents=True, exist_ok=True)
            return _resolved
    except Exception:
        pass

    # 3. Default: ~/.hort/instances/{instance_id}/
    # Instance ID is per project directory — stored in .hort-instance in the
    # project root. Each project dir that runs hort gets a unique ID.
    _resolved = Path.home() / ".hort" / "instances" / _get_instance_id()
    _resolved.mkdir(parents=True, exist_ok=True)
    return _resolved


def _get_instance_id() -> str:
    """Get or create a stable instance ID for this project directory.

    Stored in ``.hort-instance`` in the current working directory (or the
    directory where hort-config.yaml lives). Generated on first ``hort start``.
    Format: 8-char hex.

    Three instances in the same home dir = three different project dirs =
    three different IDs = three different data directories.
    """
    # Look for .hort-instance in cwd or parent dirs (up to 5 levels)
    search = Path.cwd()
    for _ in range(5):
        id_file = search / ".hort-instance"
        if id_file.exists():
            instance_id = id_file.read_text().strip()
            if instance_id:
                return instance_id
        # Also check if hort-config.yaml is here (project root marker)
        if (search / "hort-config.yaml").exists():
            break
        parent = search.parent
        if parent == search:
            break
        search = parent

    # Create new ID in the project root (where hort-config.yaml is, or cwd)
    project_root = search
    id_file = project_root / ".hort-instance"
    import uuid
    instance_id = uuid.uuid4().hex[:8]
    id_file.write_text(instance_id + "\n")
    return instance_id
    _resolved.mkdir(parents=True, exist_ok=True)
    return _resolved


def storage_dir(llming_name: str) -> Path:
    """Persistent storage for a llming: {data_dir}/storage/{llming}/"""
    p = get_data_dir() / "storage" / llming_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def runtime_dir(llming_name: str) -> Path:
    """Runtime (ephemeral) storage for a llming: {data_dir}/runtime/{llming}/"""
    p = get_data_dir() / "runtime" / llming_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def pid_dir() -> Path:
    """PID files: {data_dir}/pids/"""
    p = get_data_dir() / "pids"
    p.mkdir(parents=True, exist_ok=True)
    return p


def ipc_dir() -> Path:
    """IPC sockets: {data_dir}/ipc/"""
    p = get_data_dir() / "ipc"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    """Log files: {data_dir}/logs/"""
    p = get_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def reset() -> None:
    """Reset cached path (for testing)."""
    global _resolved
    _resolved = None
