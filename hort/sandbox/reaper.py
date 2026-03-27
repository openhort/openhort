"""Session cleanup — timeout, count limits, and space limits.

The reaper removes sandbox sessions that have expired or that push
resource usage over configured thresholds.  Policies are composable:
``reap()`` runs all enabled policies in priority order.

Policy order:
    1. **Expired** — sessions idle beyond their ``timeout_minutes``
    2. **Count**   — oldest sessions removed when count > max
    3. **Space**   — oldest sessions removed when total volume size > max
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone

from .session import VOLUME_PREFIX, SessionManager


def reap_expired(manager: SessionManager) -> list[str]:
    """Remove sessions idle longer than their configured timeout."""
    destroyed: list[str] = []
    now = datetime.now(timezone.utc)

    for session in manager.list_sessions():
        timeout = session.meta.config.timeout_minutes
        last = datetime.fromisoformat(session.meta.last_active)
        if now - last > timedelta(minutes=timeout):
            session.destroy()
            destroyed.append(session.id)

    return destroyed


def reap_by_count(
    manager: SessionManager, max_sessions: int,
) -> list[str]:
    """Remove oldest sessions when count exceeds *max_sessions*."""
    sessions = manager.list_sessions()
    if len(sessions) <= max_sessions:
        return []

    # list_sessions returns newest-first; reverse to get oldest-first
    oldest_first = list(reversed(sessions))
    to_remove = len(sessions) - max_sessions
    destroyed: list[str] = []

    for session in oldest_first[:to_remove]:
        session.destroy()
        destroyed.append(session.id)

    return destroyed


# ── Volume size measurement ────────────────────────────────────────


def _parse_size(s: str) -> int:
    """Parse a Docker size string (e.g. ``10.5MB``) to bytes."""
    match = re.match(r"([\d.]+)\s*([KMGT]?B)", s, re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }
    return int(value * multipliers.get(unit, 1))


def _get_volume_sizes() -> dict[str, int]:
    """Return ``{volume_name: size_bytes}`` for openhort volumes."""
    result = subprocess.run(
        ["docker", "system", "df", "-v"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}

    sizes: dict[str, int] = {}
    in_volumes = False
    for line in result.stdout.splitlines():
        if "VOLUME NAME" in line:
            in_volumes = True
            continue
        if in_volumes:
            if not line.strip():
                break
            parts = line.split()
            if len(parts) >= 3 and parts[0].startswith(VOLUME_PREFIX):
                sizes[parts[0]] = _parse_size(parts[-1])

    return sizes


def reap_by_space(
    manager: SessionManager, max_bytes: int,
) -> list[str]:
    """Remove oldest sessions until total volume space <= *max_bytes*."""
    volumes = _get_volume_sizes()
    total = sum(volumes.values())
    if total <= max_bytes:
        return []

    sessions = manager.list_sessions()
    oldest_first = list(reversed(sessions))

    destroyed: list[str] = []
    for session in oldest_first:
        if total <= max_bytes:
            break
        vol_size = volumes.get(session.volume_name, 0)
        session.destroy()
        destroyed.append(session.id)
        total -= vol_size

    return destroyed


def reap(
    manager: SessionManager,
    *,
    max_sessions: int | None = None,
    max_bytes: int | None = None,
) -> list[str]:
    """Run all cleanup policies.  Returns IDs of destroyed sessions.

    Always runs expired-session cleanup.  *max_sessions* and
    *max_bytes* are optional additional limits.
    """
    destroyed: list[str] = []
    destroyed.extend(reap_expired(manager))

    if max_sessions is not None:
        destroyed.extend(reap_by_count(manager, max_sessions))

    if max_bytes is not None:
        destroyed.extend(reap_by_space(manager, max_bytes))

    return destroyed
