"""Programmatic icon generation for the status bar.

Draws a simple monochrome "H" icon with a status dot, avoiding
the need for bundled image assets.
"""

from __future__ import annotations

import AppKit
import Foundation


def create_statusbar_icon(active: bool = False, warning: bool = False) -> AppKit.NSImage:
    """Create a template-style status bar icon.

    Args:
        active: Server is running (shows green dot).
        warning: Missing permissions (shows yellow dot).

    Returns:
        An NSImage sized for the menu bar (18x18 points).
    """
    size = Foundation.NSMakeSize(18, 18)
    image = AppKit.NSImage.alloc().initWithSize_(size)
    image.lockFocus()

    # Draw "H" letter in a rounded rect
    rect = Foundation.NSMakeRect(2, 2, 14, 14)
    path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 3, 3)

    AppKit.NSColor.labelColor().setStroke()
    path.setLineWidth_(1.5)
    path.stroke()

    # Draw the "H"
    attrs = {
        AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
            10, AppKit.NSFontWeightBold
        ),
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
    }
    h_str = AppKit.NSAttributedString.alloc().initWithString_attributes_("H", attrs)
    h_size = h_str.size()
    h_str.drawAtPoint_(
        Foundation.NSMakePoint(
            (18 - h_size.width) / 2,
            (18 - h_size.height) / 2 - 0.5,
        )
    )

    # Status dot (top-right corner)
    if active or warning:
        dot_rect = Foundation.NSMakeRect(12, 12, 5, 5)
        dot = AppKit.NSBezierPath.bezierPathWithOvalInRect_(dot_rect)
        if warning:
            AppKit.NSColor.systemYellowColor().setFill()
        else:
            AppKit.NSColor.systemGreenColor().setFill()
        dot.fill()

    image.unlockFocus()
    image.setTemplate_(not (active or warning))
    return image
