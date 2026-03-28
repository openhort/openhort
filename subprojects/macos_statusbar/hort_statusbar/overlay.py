"""Floating overlay banner showing active remote viewer count.

A semi-transparent, always-on-top, click-through window positioned just
below the menu bar — similar to the macOS screen recording indicator.
Visible on all Spaces.
"""

from __future__ import annotations

import logging

import AppKit
import Foundation

logger = logging.getLogger(__name__)

BANNER_WIDTH = 320
BANNER_HEIGHT = 32
BANNER_Y_OFFSET = 45  # pixels below top of screen (below menu bar)
CORNER_RADIUS = 8


class ViewerOverlay:
    """Floating banner that warns the local user about active remote viewers."""

    def __init__(self) -> None:
        self._window: AppKit.NSWindow | None = None
        self._label: AppKit.NSTextField | None = None
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if not value:
            self.hide()

    def show(self, viewer_count: int) -> None:
        """Show or update the overlay with current viewer count."""
        if not self._enabled:
            return

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: self._show_on_main(viewer_count)
        )

    def _show_on_main(self, count: int) -> None:
        """Must run on main thread (AppKit requirement)."""
        if self._window is None:
            self._create_window()

        assert self._label is not None
        suffix = "s" if count != 1 else ""
        self._label.setStringValue_(
            f"  \u25cf  Remote viewing active \u2014 {count} viewer{suffix}"
        )
        assert self._window is not None
        self._window.orderFront_(None)

    def _create_window(self) -> None:
        screen = AppKit.NSScreen.mainScreen().frame()
        x = (screen.size.width - BANNER_WIDTH) / 2
        y = screen.size.height - BANNER_Y_OFFSET

        rect = Foundation.NSMakeRect(x, y, BANNER_WIDTH, BANNER_HEIGHT)

        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )

        # Floating, always-on-top, transparent, click-through
        self._window.setLevel_(AppKit.NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(0.85, 0.15, 0.15, 0.9)
        )
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        # Round corners
        content_view = self._window.contentView()
        content_view.setWantsLayer_(True)
        content_view.layer().setCornerRadius_(CORNER_RADIUS)
        content_view.layer().setMasksToBounds_(True)

        # Label
        self._label = AppKit.NSTextField.labelWithString_("")
        self._label.setFrame_(Foundation.NSMakeRect(0, 0, BANNER_WIDTH, BANNER_HEIGHT))
        self._label.setAlignment_(AppKit.NSTextAlignmentCenter)
        self._label.setTextColor_(AppKit.NSColor.whiteColor())
        self._label.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(13, AppKit.NSFontWeightMedium)
        )
        self._label.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._label.setBezeled_(False)
        self._label.setEditable_(False)

        content_view.addSubview_(self._label)

    def hide(self) -> None:
        """Hide the overlay (no viewers connected)."""
        if self._window:
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: self._window.orderOut_(None) if self._window else None
            )
