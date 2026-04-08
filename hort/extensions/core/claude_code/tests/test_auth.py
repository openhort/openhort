"""Tests for Claude Code authentication (cross-platform credential extraction)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hort.extensions.core.claude_code.auth import get_oauth_token, get_api_key


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


@patch(
    "subprocess.check_output",
    side_effect=subprocess.CalledProcessError(1, "security"),
)
def test_get_oauth_token_keychain_missing(mock_out: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="No OAuth token"):
        get_oauth_token()


@patch("subprocess.check_output", return_value="not json")
def test_get_oauth_token_bad_json(mock_out: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="No OAuth token"):
        get_oauth_token()


@patch("subprocess.check_output", return_value='{"other": "data"}')
def test_get_oauth_token_missing_key(mock_out: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="No OAuth token"):
        get_oauth_token()


# ── get_api_key ─────────────────────────────────────────────────────


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-api-test"})
def test_get_api_key_from_env() -> None:
    assert get_api_key() == "sk-ant-api-test"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""})
@patch("subprocess.check_output")
def test_get_api_key_from_keychain(mock_out: MagicMock) -> None:
    creds = {"claudeAiOauth": {"accessToken": "sk-ant-oat01-from-keychain"}}
    mock_out.return_value = json.dumps(creds)
    assert get_api_key() == "sk-ant-oat01-from-keychain"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""})
@patch(
    "subprocess.check_output",
    side_effect=subprocess.CalledProcessError(1, "security"),
)
def test_get_api_key_nothing_available(mock_out: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="No Claude credentials"):
        get_api_key()
