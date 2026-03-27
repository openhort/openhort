"""Claude-specific authentication — macOS Keychain extraction."""

from __future__ import annotations

import json
import subprocess


def get_oauth_token() -> str:
    """Extract the Claude OAuth access token from the macOS Keychain.

    Returns the raw access token string.
    Raises RuntimeError if the token can't be found.
    """
    try:
        raw = subprocess.check_output(
            ["security", "find-generic-password",
             "-s", "Claude Code-credentials", "-w"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(
            "Could not read Claude credentials from macOS Keychain. "
            "Make sure you're logged in to Claude Code locally first."
        ) from exc

    try:
        creds = json.loads(raw)
        token = creds["claudeAiOauth"]["accessToken"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError(
            "Keychain entry found but could not parse OAuth token."
        ) from exc

    return token
