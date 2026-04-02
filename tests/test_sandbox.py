"""Tests for the sandbox session system."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from hort.sandbox import (
    CONTAINER_PREFIX,
    DEFAULT_IMAGE,
    SECCOMP_PROFILE,
    VOLUME_PREFIX,
    SecurityProfile,
    Session,
    SessionConfig,
    SessionManager,
    SessionMeta,
)


# ── Helpers ────────────────────────────────────────────────────────


def _make_meta(**overrides: object) -> SessionMeta:
    defaults = {
        "id": "abc123def456",
        "container_name": f"{CONTAINER_PREFIX}-abc123def456",
        "volume_name": f"{VOLUME_PREFIX}-abc123def456",
        "config": SessionConfig(),
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_active": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return SessionMeta(**defaults)  # type: ignore[arg-type]


def _make_session(tmp_path: Path, **overrides: object) -> Session:
    return Session(_make_meta(**overrides), tmp_path)


# ── SessionConfig ──────────────────────────────────────────────────


def test_config_defaults() -> None:
    cfg = SessionConfig()
    assert cfg.image == DEFAULT_IMAGE
    assert cfg.memory is None
    assert cfg.cpus is None
    assert cfg.timeout_minutes == 60
    assert cfg.env == {}


def test_config_custom() -> None:
    cfg = SessionConfig(
        image="custom:v1", memory="2g", cpus=4, disk="10g",
        env={"K": "V"}, timeout_minutes=120,
    )
    assert cfg.image == "custom:v1"
    assert cfg.memory == "2g"
    assert cfg.cpus == 4
    assert cfg.env == {"K": "V"}


# ── Session state queries ──────────────────────────────────────────


@patch("subprocess.run")
def test_is_running_true(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
    s = _make_session(tmp_path)
    assert s.is_running() is True


@patch("subprocess.run")
def test_is_running_false(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="false\n")
    s = _make_session(tmp_path)
    assert s.is_running() is False


@patch("subprocess.run")
def test_container_exists_true(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    s = _make_session(tmp_path)
    assert s.container_exists() is True


@patch("subprocess.run")
def test_container_exists_false(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=1)
    s = _make_session(tmp_path)
    assert s.container_exists() is False


# ── Session start ──────────────────────────────────────────────────


@patch("subprocess.run")
def test_start_creates_container(mock_run: MagicMock, tmp_path: Path) -> None:
    # is_running → False, container_exists → False
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout=""),       # is_running
        MagicMock(returncode=1),                   # container_exists
        MagicMock(returncode=0),                   # docker run
    ]
    cfg = SessionConfig(memory="512m", cpus=2, env={"KEY": "val"})
    s = _make_session(tmp_path, config=cfg)
    s.start()

    run_call = mock_run.call_args_list[2]
    cmd = run_call[0][0]
    assert "docker" in cmd
    assert "run" in cmd
    assert "-d" in cmd
    assert "--memory" in cmd
    assert "512m" in cmd
    assert "--cpus" in cmd
    assert "-e" in cmd


@patch("subprocess.run")
def test_start_resumes_stopped(mock_run: MagicMock, tmp_path: Path) -> None:
    # is_running → False, container_exists → True
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout=""),       # is_running
        MagicMock(returncode=0),                   # container_exists
        MagicMock(returncode=0),                   # docker start
    ]
    s = _make_session(tmp_path)
    s.start()

    start_call = mock_run.call_args_list[2]
    cmd = start_call[0][0]
    assert "docker" in cmd
    assert "start" in cmd
    assert s.container_name in cmd


@patch("subprocess.run")
def test_start_already_running(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
    s = _make_session(tmp_path)
    s.start()
    # Only the is_running check, no docker run/start
    assert mock_run.call_count == 1


# ── Session stop / destroy ─────────────────────────────────────────


@patch("subprocess.run")
def test_stop(mock_run: MagicMock, tmp_path: Path) -> None:
    # is_running → True, then docker stop
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="true\n"),  # is_running
        MagicMock(returncode=0),                    # docker stop
    ]
    s = _make_session(tmp_path)
    s.stop()

    stop_call = mock_run.call_args_list[1]
    cmd = stop_call[0][0]
    assert "stop" in cmd
    assert s.container_name in cmd


@patch("subprocess.run")
def test_destroy(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    s = _make_session(tmp_path)
    # Create meta file first
    s._save()
    assert s._meta_path.exists()

    s.destroy()

    # docker rm + docker volume rm
    cmds = [c[0][0] for c in mock_run.call_args_list]
    assert any("rm" in c and s.container_name in c for c in cmds)
    assert any("volume" in c and s.volume_name in c for c in cmds)
    assert not s._meta_path.exists()


# ── Session exec ───────────────────────────────────────────────────


@patch("subprocess.Popen")
@patch("subprocess.run")
def test_exec_streaming(
    mock_run: MagicMock, mock_popen: MagicMock, tmp_path: Path,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
    mock_popen.return_value = MagicMock()
    s = _make_session(tmp_path)
    proc = s.exec_streaming(["echo", "hello"])

    popen_cmd = mock_popen.call_args[0][0]
    assert "docker" in popen_cmd
    assert "exec" in popen_cmd
    assert "echo" in popen_cmd
    assert "hello" in popen_cmd


@patch("subprocess.run")
def test_exec_blocking(mock_run: MagicMock, tmp_path: Path) -> None:
    # is_running → True, then docker exec
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="true\n"),
        MagicMock(returncode=0, stdout=b"output"),
    ]
    s = _make_session(tmp_path)
    s.exec(["ls", "-la"])

    exec_call = mock_run.call_args_list[1]
    cmd = exec_call[0][0]
    assert "exec" in cmd


# ── Session write_file ─────────────────────────────────────────────


@patch("subprocess.run")
def test_write_file(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="true\n"),  # is_running
        MagicMock(returncode=0),                    # docker exec cat
    ]
    s = _make_session(tmp_path)
    s.write_file("/tmp/test.txt", "hello world")

    write_call = mock_run.call_args_list[1]
    assert write_call.kwargs.get("input") == b"hello world"


# ── Session _build_run_cmd ─────────────────────────────────────────


def test_build_run_cmd_full(tmp_path: Path) -> None:
    cfg = SessionConfig(
        image="my-image:v2",
        memory="1g",
        cpus=2.5,
        disk="5g",
        env={"A": "1", "B": "2"},
    )
    s = _make_session(tmp_path, config=cfg)
    cmd = s._build_run_cmd()

    assert cmd[0] == "docker"
    assert "run" in cmd
    assert "-d" in cmd
    assert "--name" in cmd
    assert s.container_name in cmd
    assert f"{s.volume_name}:/workspace" in cmd[cmd.index("-v") + 1]
    assert "--memory" in cmd
    assert "1g" in cmd
    assert "--cpus" in cmd
    assert "2.5" in cmd
    assert "--storage-opt" in cmd
    assert "my-image:v2" in cmd
    # env vars
    e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
    env_vals = [cmd[i + 1] for i in e_indices]
    assert "A=1" in env_vals
    assert "B=2" in env_vals


def test_build_run_cmd_minimal(tmp_path: Path) -> None:
    s = _make_session(tmp_path, config=SessionConfig())
    cmd = s._build_run_cmd()

    assert "--memory" not in cmd
    assert "--cpus" not in cmd
    assert "--storage-opt" not in cmd
    assert DEFAULT_IMAGE in cmd


# ── Security layers ───────────────────────────────────────────────


def test_security_profile_defaults() -> None:
    sec = SecurityProfile()
    assert sec.enabled is True
    assert sec.cap_drop_all is True
    assert sec.cap_add == ["NET_BIND_SERVICE"]
    assert sec.seccomp_profile == SECCOMP_PROFILE
    assert sec.no_new_privileges is True
    assert sec.read_only_root is True
    assert sec.pids_limit == 256
    assert "/tmp" in sec.tmpfs_mounts
    assert "/run" in sec.tmpfs_mounts


def test_build_run_cmd_layer2_capabilities(tmp_path: Path) -> None:
    """Layer 2: All capabilities dropped, only minimum added back."""
    s = _make_session(tmp_path, config=SessionConfig())
    cmd = s._build_run_cmd()
    assert "--cap-drop=ALL" in cmd
    assert "--cap-add=NET_BIND_SERVICE" in cmd


def test_build_run_cmd_layer3_seccomp(tmp_path: Path) -> None:
    """Layer 3: Seccomp profile applied."""
    s = _make_session(tmp_path, config=SessionConfig())
    cmd = s._build_run_cmd()
    seccomp_flags = [c for c in cmd if "seccomp=" in c]
    assert len(seccomp_flags) == 1
    assert SECCOMP_PROFILE in seccomp_flags[0]


def test_build_run_cmd_layer4_no_new_privileges(tmp_path: Path) -> None:
    """Layer 4: No new privileges flag set."""
    s = _make_session(tmp_path, config=SessionConfig())
    cmd = s._build_run_cmd()
    assert "--security-opt=no-new-privileges" in cmd


def test_build_run_cmd_layer5_metadata_blocked(tmp_path: Path) -> None:
    """Layer 5: Cloud metadata endpoints blocked via /etc/hosts."""
    s = _make_session(tmp_path, config=SessionConfig())
    cmd = s._build_run_cmd()
    host_entries = [c for c in cmd if c.startswith("--add-host=")]
    hosts_str = " ".join(host_entries)
    assert "169.254.169.254:127.0.0.1" in hosts_str
    assert "metadata.google.internal:127.0.0.1" in hosts_str


def test_build_run_cmd_layer6_pids_limit(tmp_path: Path) -> None:
    """Layer 6: PID limit applied."""
    s = _make_session(tmp_path, config=SessionConfig())
    cmd = s._build_run_cmd()
    assert "--pids-limit" in cmd
    idx = cmd.index("--pids-limit")
    assert cmd[idx + 1] == "256"


def test_build_run_cmd_layer7_readonly_root(tmp_path: Path) -> None:
    """Layer 7: Read-only root filesystem with writable tmpfs."""
    s = _make_session(tmp_path, config=SessionConfig())
    cmd = s._build_run_cmd()
    assert "--read-only" in cmd
    tmpfs_args = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--tmpfs"]
    assert any("/tmp:" in t for t in tmpfs_args)
    assert any("/run:" in t for t in tmpfs_args)
    # Verify noexec on tmpfs
    for t in tmpfs_args:
        assert "noexec" in t


def test_build_run_cmd_security_disabled(tmp_path: Path) -> None:
    """When security is disabled, no hardening flags are added."""
    cfg = SessionConfig(security=SecurityProfile(enabled=False))
    s = _make_session(tmp_path, config=cfg)
    cmd = s._build_run_cmd()
    assert "--cap-drop=ALL" not in cmd
    assert "--read-only" not in cmd
    assert "--pids-limit" not in cmd
    assert "--security-opt=no-new-privileges" not in cmd
    # Only the default --add-host for host.docker.internal should remain
    host_entries = [c for c in cmd if c.startswith("--add-host=")]
    assert len(host_entries) == 1  # just host.docker.internal


def test_build_run_cmd_custom_security(tmp_path: Path) -> None:
    """Custom security profile relaxes individual layers."""
    sec = SecurityProfile(
        cap_drop_all=True,
        cap_add=["NET_BIND_SERVICE", "SYS_PTRACE"],
        read_only_root=False,
        pids_limit=512,
    )
    cfg = SessionConfig(security=sec)
    s = _make_session(tmp_path, config=cfg)
    cmd = s._build_run_cmd()
    assert "--cap-drop=ALL" in cmd
    assert "--cap-add=NET_BIND_SERVICE" in cmd
    assert "--cap-add=SYS_PTRACE" in cmd
    assert "--read-only" not in cmd
    idx = cmd.index("--pids-limit")
    assert cmd[idx + 1] == "512"


# ── Metadata persistence ──────────────────────────────────────────


def test_save_and_load(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    s.meta.user_data["key"] = "value"
    s._save()

    data = json.loads(s._meta_path.read_text())
    assert data["id"] == s.id
    assert data["user_data"]["key"] == "value"


def test_touch_updates_last_active(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    old = s.meta.last_active
    s._touch()
    assert s.meta.last_active != old


# ── SessionManager ─────────────────────────────────────────────────


def test_manager_create(tmp_path: Path) -> None:
    mgr = SessionManager(store_dir=tmp_path)
    s = mgr.create(SessionConfig(memory="256m"))
    assert len(s.id) == 12
    assert s.meta.config.memory == "256m"
    assert (tmp_path / f"{s.id}.json").exists()


def test_manager_get(tmp_path: Path) -> None:
    mgr = SessionManager(store_dir=tmp_path)
    s = mgr.create()
    loaded = mgr.get(s.id)
    assert loaded is not None
    assert loaded.id == s.id


def test_manager_get_missing(tmp_path: Path) -> None:
    mgr = SessionManager(store_dir=tmp_path)
    assert mgr.get("nonexistent") is None


def test_manager_list(tmp_path: Path) -> None:
    mgr = SessionManager(store_dir=tmp_path)
    mgr.create()
    mgr.create()
    mgr.create()
    assert len(mgr.list_sessions()) == 3


@patch("subprocess.run")
def test_manager_destroy(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    mgr = SessionManager(store_dir=tmp_path)
    s = mgr.create()
    sid = s.id

    assert mgr.destroy(sid) is True
    assert not (tmp_path / f"{sid}.json").exists()
    assert mgr.destroy(sid) is False


def test_manager_list_order(tmp_path: Path) -> None:
    """list_sessions returns newest-first."""
    mgr = SessionManager(store_dir=tmp_path)
    s1 = mgr.create()
    s1.meta.last_active = "2026-01-01T00:00:00+00:00"
    s1._save()
    s2 = mgr.create()
    s2.meta.last_active = "2026-06-01T00:00:00+00:00"
    s2._save()

    sessions = mgr.list_sessions()
    assert sessions[0].id == s2.id
    assert sessions[1].id == s1.id


# ── Image management ──────────────────────────────────────────────


@patch("subprocess.run")
def test_image_ready_true(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    assert SessionManager.image_ready() is True


@patch("subprocess.run")
def test_image_ready_false(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1)
    assert SessionManager.image_ready() is False


@patch("subprocess.run")
def test_build_image(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    SessionManager.build_image(image="test:v1", dockerfile_dir="/tmp")
    cmd = mock_run.call_args[0][0]
    assert "build" in cmd
    assert "test:v1" in cmd
    assert "/tmp" in cmd
