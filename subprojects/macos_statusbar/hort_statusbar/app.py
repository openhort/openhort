"""Main application — orchestrates menu bar, server bridge, power, and overlay.

AppKit owns the main thread. The asyncio event loop (server bridge polling)
runs on a background daemon thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading

import AppKit

from hort_statusbar.menubar import MenuBarAgent
from hort_statusbar.overlay import ViewerOverlay
from hort_statusbar.power import PowerManager
from hort_statusbar.server_bridge import ServerBridge, ServerStatus

logger = logging.getLogger(__name__)


class HortStatusBarApp:
    """macOS status bar application for openhort.

    Thread model:
        Main thread  — AppKit run loop (menu bar, overlay, permissions)
        Background   — asyncio event loop (server bridge, status polling)

    Communication:
        main -> bg:  loop.call_soon_threadsafe()
        bg -> main:  NSOperationQueue.mainQueue().addOperationWithBlock_()
    """

    def __init__(self) -> None:
        self.power = PowerManager()
        self.overlay = ViewerOverlay()
        self.bridge = ServerBridge(on_status_change=self._on_status_change)
        self.menubar = MenuBarAgent(self)

        self._bg_loop: asyncio.AbstractEventLoop | None = None
        self._bg_thread: threading.Thread | None = None

    def run(self) -> None:
        """Start the app. Blocks on NSApplication.run() (main thread)."""
        ns_app = AppKit.NSApplication.sharedApplication()
        # Accessory = no Dock icon, menu bar only
        ns_app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        # Initialize state
        self._init_state()

        # Start background event loop for server polling
        self._start_background_loop()

        logger.info("openhort status bar app started")

        # Block on AppKit run loop — handles menu bar + overlay
        AppKit.NSApp.run()

    def _init_state(self) -> None:
        """Initialize state from current system."""
        from hort_statusbar import autostart
        from hort_statusbar.permissions import check_permissions

        # Reflect autostart state
        self.menubar.update_autostart(autostart.is_installed())

        # Check permissions
        perms = check_permissions()
        self.menubar.update_permissions(perms.all_granted)
        if not perms.all_granted:
            logger.warning("Missing permissions: %s", perms.summary)

        # Enable sleep prevention by default
        self.power.prevent_sleep()

        # Check if server is already running
        if self.bridge._is_port_in_use():
            self.bridge._status.running = True
            self.menubar.update_server_status(running=True, observers=0)

    # --- Server control ---

    def start_server(self) -> None:
        """Start the openhort server."""
        self.bridge.start_server()

    def stop_server(self) -> None:
        """Stop the openhort server."""
        self.bridge.stop_server()
        self.overlay.hide()

    # --- Background asyncio loop ---

    def _start_background_loop(self) -> None:
        """Start a daemon thread running an asyncio event loop for polling."""
        self._bg_thread = threading.Thread(
            target=self._run_background_loop,
            daemon=True,
            name="hort-statusbar-bg",
        )
        self._bg_thread.start()

    def _run_background_loop(self) -> None:
        """Background thread entry — runs asyncio polling."""
        self._bg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._bg_loop)
        self._bg_loop.run_until_complete(self.bridge.start_polling())

    # --- Status change callback (called from background thread) ---

    def _on_status_change(self, status: ServerStatus) -> None:
        """Called by ServerBridge when status changes. Dispatches to main thread."""
        self.menubar.update_server_status(
            running=status.running,
            observers=status.observers,
            version=status.version,
        )

        if status.observers > 0:
            self.overlay.show(status.observers)
        else:
            self.overlay.hide()

    # --- Shutdown ---

    def quit(self) -> None:
        """Full shutdown — stop server, release assertions, quit app."""
        logger.info("Shutting down")

        # Stop polling
        if self._bg_loop:
            self._bg_loop.call_soon_threadsafe(self._bg_loop.stop)

        # Release power assertions
        self.power.allow_sleep()

        # Hide overlay
        self.overlay.hide()

        # Quit AppKit
        AppKit.NSApp.terminate_(None)
