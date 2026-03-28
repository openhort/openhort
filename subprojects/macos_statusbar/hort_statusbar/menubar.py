"""Menu bar status item with server controls and live status."""

from __future__ import annotations

import logging
import webbrowser
from typing import TYPE_CHECKING

import AppKit
import Foundation
import objc

from hort_statusbar.icons import create_statusbar_icon

if TYPE_CHECKING:
    from hort_statusbar.app import HortStatusBarApp

logger = logging.getLogger(__name__)


class MenuBarAgent:
    """NSStatusItem-based menu bar agent.

    Provides:
    - Server status indicator (icon color/dot)
    - Start / Stop server toggle
    - Viewer count display
    - Open in browser, copy URL
    - Settings submenu (sleep prevention, auto-start, overlay toggle)
    - Permissions status
    - Quit
    """

    def __init__(self, app: HortStatusBarApp) -> None:
        self._app = app
        self._status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        self._setup_icon(active=False)
        self._build_menu()

    # --- Icon ---

    def _setup_icon(self, active: bool = False, warning: bool = False) -> None:
        button = self._status_item.button()
        button.setImage_(create_statusbar_icon(active=active, warning=warning))
        button.setToolTip_("openhort \u2014 Remote Window Viewer")

    # --- Menu construction ---

    def _build_menu(self) -> None:
        menu = AppKit.NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)

        # Status section
        self._server_status_item = self._add_label(menu, "Server: Stopped")
        self._viewers_item = self._add_label(menu, "No active viewers")
        self._version_item = self._add_label(menu, "")
        self._version_item.setHidden_(True)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Controls
        self._start_stop_item = self._add_action(menu, "Start Server", "toggleServer:")
        self._open_browser_item = self._add_action(menu, "Open in Browser\u2026", "openBrowser:")
        self._open_browser_item.setEnabled_(False)
        self._copy_url_item = self._add_action(menu, "Copy URL", "copyURL:")
        self._copy_url_item.setEnabled_(False)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Settings submenu
        settings_menu = AppKit.NSMenu.alloc().init()
        settings_menu.setAutoenablesItems_(False)

        self._sleep_item = self._add_action(settings_menu, "Prevent Sleep", "toggleSleep:")
        self._sleep_item.setState_(AppKit.NSControlStateValueOn)

        self._display_sleep_item = self._add_action(
            settings_menu, "Keep Display On", "toggleDisplaySleep:"
        )
        self._display_sleep_item.setState_(AppKit.NSControlStateValueOff)

        self._overlay_item = self._add_action(
            settings_menu, "Show Viewer Warning", "toggleOverlay:"
        )
        self._overlay_item.setState_(AppKit.NSControlStateValueOn)

        settings_menu.addItem_(AppKit.NSMenuItem.separatorItem())

        self._autostart_item = self._add_action(
            settings_menu, "Start on Login", "toggleAutostart:"
        )

        settings_parent = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings", None, ""
        )
        settings_parent.setSubmenu_(settings_menu)
        menu.addItem_(settings_parent)

        # Permissions
        self._permissions_item = self._add_action(
            menu, "Check Permissions\u2026", "checkPermissions:"
        )

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        self._add_action(menu, "Quit openhort", "quitApp:")

        self._status_item.setMenu_(menu)

    # --- Menu helpers ---

    def _add_label(self, menu: AppKit.NSMenu, title: str) -> AppKit.NSMenuItem:
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, None, ""
        )
        item.setEnabled_(False)
        menu.addItem_(item)
        return item

    def _add_action(
        self, menu: AppKit.NSMenu, title: str, selector: str
    ) -> AppKit.NSMenuItem:
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, objc.selector(None, selector=selector.encode(), signature=b"v@:@"), ""
        )
        item.setTarget_(self)
        menu.addItem_(item)
        return item

    # --- Status updates (called from any thread) ---

    def update_server_status(self, running: bool, observers: int, version: str = "") -> None:
        """Update the menu bar to reflect current server state."""
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: self._do_update(running, observers, version)
        )

    def _do_update(self, running: bool, observers: int, version: str) -> None:
        if running:
            self._server_status_item.setTitle_("Server: Running")
            self._start_stop_item.setTitle_("Stop Server")
            self._open_browser_item.setEnabled_(True)
            self._copy_url_item.setEnabled_(True)
            self._setup_icon(active=True)
        else:
            self._server_status_item.setTitle_("Server: Stopped")
            self._start_stop_item.setTitle_("Start Server")
            self._open_browser_item.setEnabled_(False)
            self._copy_url_item.setEnabled_(False)
            self._setup_icon(active=False)

        if observers > 0:
            suffix = "s" if observers != 1 else ""
            self._viewers_item.setTitle_(f"{observers} viewer{suffix} connected")
        else:
            self._viewers_item.setTitle_("No active viewers")

        if version:
            self._version_item.setTitle_(f"v{version}")
            self._version_item.setHidden_(False)
        else:
            self._version_item.setHidden_(True)

    def update_autostart(self, installed: bool) -> None:
        """Reflect autostart state in the menu."""
        state = AppKit.NSControlStateValueOn if installed else AppKit.NSControlStateValueOff
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: self._autostart_item.setState_(state)
        )

    def update_permissions(self, all_ok: bool) -> None:
        """Show warning icon if permissions are missing."""
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: self._setup_icon(
                active=self._app.bridge.is_running,
                warning=not all_ok,
            )
        )

    # --- Actions (selectors called by AppKit) ---

    @objc.typedSelector(b"v@:@")
    def toggleServer_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        if self._app.bridge.is_running:
            self._app.stop_server()
        else:
            self._app.start_server()

    @objc.typedSelector(b"v@:@")
    def openBrowser_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        url = self._app.bridge.status.http_url or "http://localhost:8940"
        webbrowser.open(url)

    @objc.typedSelector(b"v@:@")
    def copyURL_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        url = self._app.bridge.status.http_url or "http://localhost:8940"
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(url, AppKit.NSPasteboardTypeString)

    @objc.typedSelector(b"v@:@")
    def toggleSleep_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        if self._app.power.is_preventing_sleep:
            self._app.power.allow_sleep()
            sender.setState_(AppKit.NSControlStateValueOff)
        else:
            self._app.power.prevent_sleep()
            sender.setState_(AppKit.NSControlStateValueOn)

    @objc.typedSelector(b"v@:@")
    def toggleDisplaySleep_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        if self._app.power.is_preventing_display_sleep:
            self._app.power.allow_sleep()
            self._app.power.prevent_sleep(prevent_display_sleep=False)
            sender.setState_(AppKit.NSControlStateValueOff)
        else:
            self._app.power.prevent_sleep(prevent_display_sleep=True)
            sender.setState_(AppKit.NSControlStateValueOn)

    @objc.typedSelector(b"v@:@")
    def toggleOverlay_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        self._app.overlay.enabled = not self._app.overlay.enabled
        state = (
            AppKit.NSControlStateValueOn
            if self._app.overlay.enabled
            else AppKit.NSControlStateValueOff
        )
        sender.setState_(state)

    @objc.typedSelector(b"v@:@")
    def toggleAutostart_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        from hort_statusbar import autostart

        if autostart.is_installed():
            autostart.uninstall()
            sender.setState_(AppKit.NSControlStateValueOff)
        else:
            autostart.install()
            sender.setState_(AppKit.NSControlStateValueOn)

    @objc.typedSelector(b"v@:@")
    def checkPermissions_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        from hort_statusbar.permissions import check_permissions, request_all_permissions

        status = check_permissions()
        if status.all_granted:
            self._show_alert("Permissions", "All permissions are granted.")
        else:
            request_all_permissions()

    @objc.typedSelector(b"v@:@")
    def quitApp_(self, sender: AppKit.NSMenuItem) -> None:  # noqa: N802
        self._app.quit()

    # --- Helpers ---

    def _show_alert(self, title: str, message: str) -> None:
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("OK")
        alert.runModal()
