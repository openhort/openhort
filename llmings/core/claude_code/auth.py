"""Claude Code authentication — cross-platform credential extraction.

Supports macOS Keychain, Linux libsecret, and Windows Credential Manager.
Falls back to ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess

logger = logging.getLogger(__name__)


def get_api_key() -> str:
    """Get an API key or OAuth token for Claude.

    Tries (in order):
    1. ``ANTHROPIC_API_KEY`` environment variable
    2. OAuth access token from the OS credential store

    Returns the raw key/token string.
    Raises RuntimeError if nothing is available.
    """
    # 1. Explicit API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        logger.info("Using ANTHROPIC_API_KEY from environment")
        return api_key

    # 2. OS credential store (OAuth)
    try:
        creds = _read_credential_store()
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if token:
            logger.info("Using OAuth token from OS credential store")
            return token
    except Exception as exc:
        logger.debug("OS credential store unavailable: %s", exc)

    raise RuntimeError(
        "No Claude credentials found. Either set ANTHROPIC_API_KEY "
        "or log in to Claude Code (`claude login`)."
    )


def get_oauth_token() -> str:
    """Extract the OAuth access token from the OS credential store.

    Returns the raw access token string.
    Raises RuntimeError if not available.
    """
    try:
        creds = _read_credential_store()
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if token:
            return token
    except Exception:
        pass
    raise RuntimeError("No OAuth token available")


def _read_credential_store() -> dict:
    """Read Claude Code credentials from the OS-native credential store.

    - macOS: Keychain (``security`` CLI)
    - Linux: libsecret (``secret-tool`` CLI)
    - Windows: Credential Manager (``cmdkey`` + PowerShell)
    """
    system = platform.system()
    if system == "Darwin":
        return _read_macos_keychain()
    elif system == "Linux":
        return _read_linux_libsecret()
    elif system == "Windows":
        return _read_windows_credman()
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def _read_macos_keychain() -> dict:
    """Read from macOS Keychain."""
    raw = subprocess.check_output(
        ["security", "find-generic-password",
         "-s", "Claude Code-credentials", "-w"],
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()
    return json.loads(raw)


def _read_linux_libsecret() -> dict:
    """Read from Linux libsecret (GNOME Keyring / KDE Wallet)."""
    raw = subprocess.check_output(
        ["secret-tool", "lookup", "service", "Claude Code-credentials"],
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()
    return json.loads(raw)


def _read_windows_credman() -> dict:
    """Read from Windows Credential Manager via PowerShell."""
    ps_script = (
        '[System.Runtime.InteropServices.Marshal]::'
        'PtrToStringAuto([System.Runtime.InteropServices.Marshal]::'
        'SecureStringToBSTR((Get-StoredCredential -Target '
        '"Claude Code-credentials").Password))'
    )
    raw = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps_script],
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()
    return json.loads(raw)
