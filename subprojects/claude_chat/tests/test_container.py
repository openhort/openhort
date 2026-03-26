"""Tests for the container lifecycle module."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from subprojects.claude_chat.container import (
    CONTAINER_NAME,
    IMAGE_NAME,
    container_exists,
    container_running,
    get_oauth_token,
    image_exists,
)


# ── get_oauth_token ─────────────────────────────────────────────────


@patch("subprocess.check_output")
def test_get_oauth_token_success(mock_out: MagicMock) -> None:
    creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-test-token",
            "refreshToken": "sk-ant-ort01-refresh",
            "expiresAt": 9999999999999,
        }
    }
    mock_out.return_value = json.dumps(creds)
    assert get_oauth_token() == "sk-ant-oat01-test-token"


@patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "security"))
def test_get_oauth_token_keychain_missing(mock_out: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="macOS Keychain"):
        get_oauth_token()


@patch("subprocess.check_output", return_value="not json")
def test_get_oauth_token_bad_json(mock_out: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="parse OAuth"):
        get_oauth_token()


@patch("subprocess.check_output", return_value='{"other": "data"}')
def test_get_oauth_token_missing_key(mock_out: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="parse OAuth"):
        get_oauth_token()


# ── image_exists ────────────────────────────────────────────────────


@patch("subprocess.run")
def test_image_exists_true(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    assert image_exists() is True
    cmd = mock_run.call_args[0][0]
    assert IMAGE_NAME in cmd


@patch("subprocess.run")
def test_image_exists_false(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1)
    assert image_exists() is False


# ── container_running / container_exists ────────────────────────────


@patch("subprocess.run")
def test_container_running_true(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
    assert container_running() is True


@patch("subprocess.run")
def test_container_running_false(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="false\n")
    assert container_running() is False


@patch("subprocess.run")
def test_container_running_not_found(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    assert container_running() is False


@patch("subprocess.run")
def test_container_exists_true(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    assert container_exists() is True


@patch("subprocess.run")
def test_container_exists_false(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1)
    assert container_exists() is False
