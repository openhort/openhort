"""LaunchAgent management for auto-start on login."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LABEL = "com.openhort.statusbar"
PLIST_PATH = Path("~/Library/LaunchAgents").expanduser() / f"{LABEL}.plist"

PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>hort_statusbar</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path}</string>
    </dict>
</dict>
</plist>"""


def is_installed() -> bool:
    """Check if the LaunchAgent is installed."""
    return PLIST_PATH.exists()


def install() -> None:
    """Install the LaunchAgent for auto-start on login.

    Uses the current Python interpreter path so it works whether
    installed via pip, poetry, or pyenv.
    """
    import os

    content = PLIST_TEMPLATE.format(
        label=LABEL,
        python=sys.executable,
        path=os.environ.get("PATH", "/usr/bin:/usr/local/bin"),
    )

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(content)
    logger.info("LaunchAgent installed at %s", PLIST_PATH)

    # Load immediately
    subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        check=False,
        capture_output=True,
    )


def uninstall() -> None:
    """Remove the LaunchAgent."""
    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            check=False,
            capture_output=True,
        )
        PLIST_PATH.unlink()
        logger.info("LaunchAgent removed")
