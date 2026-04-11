"""Tests for the Claude-specific container helpers (keychain auth)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from llmings.llms.claude_code.auth import get_oauth_token


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
