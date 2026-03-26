"""Container lifecycle for the Claude Chat sandbox.

Builds, starts, stops, and executes commands inside a Docker container
that has Claude Code CLI installed. The container stays alive between
turns so ``--resume`` works against the same filesystem.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CONTAINER_NAME = "claude-chat-sandbox"
IMAGE_NAME = "claude-chat-sandbox:latest"
DOCKERFILE_DIR = str(Path(__file__).resolve().parent)


# ── Keychain ────────────────────────────────────────────────────────


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


# ── Image ───────────────────────────────────────────────────────────


def image_exists() -> bool:
    """Check if the sandbox image is already built."""
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def build_image() -> None:
    """Build the sandbox Docker image (shows progress)."""
    print(f"Building {IMAGE_NAME} ...", flush=True)
    subprocess.run(
        ["docker", "build", "-t", IMAGE_NAME, DOCKERFILE_DIR],
        check=True,
    )
    print("Image ready.\n")


# ── Container ───────────────────────────────────────────────────────


def container_running() -> bool:
    """Check if the sandbox container is running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def container_exists() -> bool:
    """Check if the sandbox container exists (running or stopped)."""
    result = subprocess.run(
        ["docker", "inspect", CONTAINER_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def ensure_container(token: str) -> None:
    """Make sure the sandbox container is running.

    Creates and starts it if necessary, passing the OAuth token
    as ANTHROPIC_API_KEY.
    """
    if container_running():
        return

    if container_exists():
        # Stopped — remove and recreate (token may have refreshed)
        subprocess.run(
            ["docker", "rm", "-f", CONTAINER_NAME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", CONTAINER_NAME,
            "-e", f"ANTHROPIC_API_KEY={token}",
            IMAGE_NAME,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def stop_container() -> None:
    """Stop and remove the sandbox container."""
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def exec_claude(args: list[str]) -> subprocess.Popen[bytes]:
    """Run ``claude`` inside the sandbox container.

    Returns a Popen with stdout piped (for stream parsing).
    The command runs with the container's ANTHROPIC_API_KEY env var.
    """
    cmd = [
        "docker", "exec", "-i",
        CONTAINER_NAME,
        "claude",
        *args,
    ]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
