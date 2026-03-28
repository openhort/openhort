"""Entry point for the openhort status bar app.

Usage:
    python -m hort_statusbar          # Start the status bar app
    python -m hort_statusbar --help   # Show help
"""

from __future__ import annotations

import logging
import sys


def main() -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        print(
            "openhort status bar — macOS menu bar app\n"
            "\n"
            "Usage:\n"
            "  python -m hort_statusbar          Start the status bar app\n"
            "  python -m hort_statusbar --help    Show this help\n"
            "\n"
            "The app sits in the macOS menu bar and lets you:\n"
            "  - Start and stop the openhort server\n"
            "  - See how many viewers are connected\n"
            "  - Prevent the Mac from sleeping\n"
            "  - Auto-start on login\n"
            "  - Show a floating warning when someone is viewing remotely\n"
        )
        return

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if sys.platform != "darwin":
        print("Error: This app requires macOS.", file=sys.stderr)
        sys.exit(1)

    from hort_statusbar.app import HortStatusBarApp

    app = HortStatusBarApp()
    app.run()


if __name__ == "__main__":
    main()
