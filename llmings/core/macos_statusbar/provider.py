"""macOS status bar plugin — launches the companion status bar process.

The status bar is a compiled Swift binary (NSApplication with NSStatusItem).
This plugin manages its lifecycle:

- On activate: ensure the binary is built, then spawn it
- On deactivate: send SIGTERM so it exits cleanly
- The status bar polls http://localhost:8940 to know the server is alive

Security: both sides share a key file at ``~/.hort/statusbar.key``.
Whoever starts first creates it; either side rotates when it's >24 h old.
The status bar sends the key as ``X-Hort-Key`` on every request.
The plugin's ``/verify`` endpoint validates with ``secrets.compare_digest``.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from hort.llming import Llming

# Project layout
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_STATUSBAR_DIR = _PROJECT_ROOT / "subprojects" / "macos_statusbar"
_STATUSBAR_BIN = _STATUSBAR_DIR / "build" / "HortStatusBar"

# Header name the status bar sends with every request
HEADER_NAME = "X-Hort-Key"

# Shared key file — both plugin and statusbar read/write this
_KEY_FILE = Path("~/.hort/statusbar.key").expanduser()

# Rotate after 24 hours
_KEY_MAX_AGE = 86400


def get_or_rotate_key() -> str:
    """Read the shared key, rotating if missing or older than 24 h.

    Uses atomic write (tempfile + rename) so concurrent starts
    don't corrupt the file. Last writer wins — both generate
    valid keys so either result is fine.
    """
    try:
        data = json.loads(_KEY_FILE.read_text())
        age = time.time() - data.get("created", 0)
        if age < _KEY_MAX_AGE and data.get("key"):
            return data["key"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # Rotate
    key = secrets.token_urlsafe(32)
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"key": key, "created": time.time()})
    # Atomic write — write to temp in same dir, then rename
    fd, tmp = tempfile.mkstemp(dir=str(_KEY_FILE.parent), suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)  # owner-only read/write
        os.write(fd, payload.encode())
        os.close(fd)
        os.replace(tmp, str(_KEY_FILE))
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    return key


class MacOSStatusBarPlugin(Llming):
    """Plugin that auto-launches the macOS status bar companion."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None

    def activate(self, config: dict[str, Any]) -> None:
        if sys.platform != "darwin":
            return

        if not self.config.get("features", {}).get("autostart", True):
            self.log.info("Status bar autostart disabled")
            return

        # Ensure key file exists (we may start before the statusbar)
        get_or_rotate_key()

        self._launch()

    def deactivate(self) -> None:
        self._terminate()

    def get_pulse(self) -> dict[str, Any]:
        alive = self._is_alive()
        return {
            "running": alive,
            "pid": self._process.pid if self._process and alive else None,
        }

    def get_router(self) -> Any:
        """Expose a /verify endpoint for the status bar handshake."""
        from fastapi import APIRouter, Header
        from fastapi.responses import JSONResponse

        router = APIRouter()

        @router.post("/verify")
        async def verify_statusbar(
            x_hort_key: str = Header("", alias=HEADER_NAME),
        ) -> JSONResponse:
            """Verify the status bar's shared key."""
            current_key = get_or_rotate_key()
            if not x_hort_key or not secrets.compare_digest(
                x_hort_key, current_key
            ):
                return JSONResponse(
                    {"ok": False, "error": "invalid key"},
                    status_code=403,
                )
            return JSONResponse({"ok": True})

        return router

    # --- Lifecycle ---

    def _launch(self) -> None:
        """Spawn the status bar as an independent process."""
        if self._is_alive():
            self.log.info("Status bar already running (PID %d)", self._process.pid)  # type: ignore[union-attr]
            return

        # Check if another instance is already running
        if self._find_existing_process():
            self.log.info("Status bar already running externally")
            return

        # Build if needed
        if not _STATUSBAR_BIN.exists():
            self.log.info("Status bar binary not found, building...")
            build_script = _STATUSBAR_DIR / "build.sh"
            if not build_script.exists():
                self.log.warning("build.sh not found at %s", build_script)
                return
            result = subprocess.run(
                ["bash", str(build_script)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.log.error("Build failed: %s", result.stderr)
                return

        self.log.info("Launching status bar: %s", _STATUSBAR_BIN)
        self._process = subprocess.Popen(
            [str(_STATUSBAR_BIN), "--managed"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach from parent process group
        )
        self.log.info("Status bar launched (PID %d)", self._process.pid)
        self.vault.set("state", {
            "running": True,
            "pid": self._process.pid,
        })

    def _terminate(self) -> None:
        """Send SIGTERM to the status bar process."""
        if not self._process:
            return

        if self._process.poll() is not None:
            self._process = None
            return

        self.log.info("Stopping status bar (PID %d)", self._process.pid)
        try:
            self._process.send_signal(signal.SIGTERM)
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.log.warning("Status bar didn't stop in 5s, sending SIGKILL")
            self._process.kill()
            self._process.wait(timeout=3)
        except ProcessLookupError:
            pass  # already exited
        self._process = None
        self.vault.set("state", {"running": False, "pid": None})

    def _is_alive(self) -> bool:
        """Check if our managed subprocess is still running."""
        return self._process is not None and self._process.poll() is None

    def _find_existing_process(self) -> bool:
        """Check if a status bar is already running."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "HortStatusBar"],
                capture_output=True,
                text=True,
            )
            return bool(result.stdout.strip())
        except Exception:
            return False
