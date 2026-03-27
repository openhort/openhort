"""Tests for the reaper cleanup policies."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hort.sandbox.reaper import (
    _parse_size,
    reap,
    reap_by_count,
    reap_by_space,
    reap_expired,
)
from hort.sandbox import SessionConfig, SessionManager


def _create_session(
    mgr: SessionManager,
    *,
    last_active: str | None = None,
    timeout_minutes: int = 60,
) -> str:
    """Create a session with controlled timestamps."""
    s = mgr.create(SessionConfig(timeout_minutes=timeout_minutes))
    if last_active:
        s.meta.last_active = last_active
        s._save()
    return s.id


# ── _parse_size ────────────────────────────────────────────────────


def test_parse_bytes() -> None:
    assert _parse_size("100B") == 100


def test_parse_kilobytes() -> None:
    assert _parse_size("1KB") == 1024


def test_parse_megabytes() -> None:
    assert _parse_size("10.5MB") == int(10.5 * 1024**2)


def test_parse_gigabytes() -> None:
    assert _parse_size("2GB") == 2 * 1024**3


def test_parse_terabytes() -> None:
    assert _parse_size("1TB") == 1024**4


def test_parse_case_insensitive() -> None:
    assert _parse_size("500mb") == 500 * 1024**2


def test_parse_invalid() -> None:
    assert _parse_size("abc") == 0


def test_parse_no_unit() -> None:
    assert _parse_size("123") == 0


# ── reap_expired ───────────────────────────────────────────────────


@patch("subprocess.run")
def test_reap_expired_removes_old(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)

    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    sid = _create_session(mgr, last_active=old_time, timeout_minutes=60)

    destroyed = reap_expired(mgr)
    assert sid in destroyed
    assert mgr.get(sid) is None


@patch("subprocess.run")
def test_reap_expired_keeps_recent(
    mock_run: MagicMock, tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)

    recent = datetime.now(timezone.utc).isoformat()
    sid = _create_session(mgr, last_active=recent, timeout_minutes=60)

    destroyed = reap_expired(mgr)
    assert destroyed == []
    assert mgr.get(sid) is not None


@patch("subprocess.run")
def test_reap_expired_respects_timeout(
    mock_run: MagicMock, tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)

    # 30 min ago, with 60 min timeout → NOT expired
    half_hour_ago = (
        datetime.now(timezone.utc) - timedelta(minutes=30)
    ).isoformat()
    sid = _create_session(
        mgr, last_active=half_hour_ago, timeout_minutes=60,
    )
    assert reap_expired(mgr) == []

    # 30 min ago, with 15 min timeout → expired
    sid2 = _create_session(
        mgr, last_active=half_hour_ago, timeout_minutes=15,
    )
    destroyed = reap_expired(mgr)
    assert sid2 in destroyed
    assert sid not in destroyed


# ── reap_by_count ──────────────────────────────────────────────────


@patch("subprocess.run")
def test_reap_by_count_under_limit(
    mock_run: MagicMock, tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)
    _create_session(mgr)
    _create_session(mgr)

    assert reap_by_count(mgr, max_sessions=5) == []


@patch("subprocess.run")
def test_reap_by_count_removes_oldest(
    mock_run: MagicMock, tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)

    oldest = _create_session(
        mgr, last_active="2026-01-01T00:00:00+00:00",
    )
    middle = _create_session(
        mgr, last_active="2026-06-01T00:00:00+00:00",
    )
    newest = _create_session(
        mgr, last_active="2026-12-01T00:00:00+00:00",
    )

    destroyed = reap_by_count(mgr, max_sessions=1)
    assert oldest in destroyed
    assert middle in destroyed
    assert newest not in destroyed


# ── reap_by_space ──────────────────────────────────────────────────


@patch("subprocess.run")
def test_reap_by_space_under_limit(
    mock_run: MagicMock, tmp_path: Path,
) -> None:
    # docker system df -v returns empty
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    mgr = SessionManager(store_dir=tmp_path)
    _create_session(mgr)

    assert reap_by_space(mgr, max_bytes=1024**3) == []


@patch("hort.sandbox.reaper._get_volume_sizes")
@patch("subprocess.run")
def test_reap_by_space_removes_oldest(
    mock_run: MagicMock,
    mock_sizes: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)

    s1 = mgr.create()
    s1.meta.last_active = "2026-01-01T00:00:00+00:00"
    s1._save()

    s2 = mgr.create()
    s2.meta.last_active = "2026-06-01T00:00:00+00:00"
    s2._save()

    # Total 300MB, limit 200MB → oldest removed
    mock_sizes.return_value = {
        s1.volume_name: 150 * 1024**2,
        s2.volume_name: 150 * 1024**2,
    }

    destroyed = reap_by_space(mgr, max_bytes=200 * 1024**2)
    assert s1.id in destroyed
    assert s2.id not in destroyed


# ── reap (combined) ────────────────────────────────────────────────


@patch("subprocess.run")
def test_reap_combined(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)

    old = _create_session(
        mgr,
        last_active=(
            datetime.now(timezone.utc) - timedelta(hours=5)
        ).isoformat(),
        timeout_minutes=60,
    )
    recent = _create_session(mgr)

    destroyed = reap(mgr, max_sessions=10)
    assert old in destroyed
    assert recent not in destroyed
