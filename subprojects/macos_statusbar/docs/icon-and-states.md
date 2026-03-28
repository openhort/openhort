# Icon & Visual States

## Icon Design

The menu bar icon is a **programmatically drawn** 18x18 point image — no bundled PNG assets. This keeps the package lightweight, resolution-independent, and trivially themeable.

The base icon is a rounded rectangle with a bold "H" letter inside. A colored status dot in the top-right corner encodes the current state.

```
  ┌──────────┐
  │ ┌──────┐ │
  │ │      │ │       18x18 points (36x36 px @2x)
  │ │  H   │ │       Rounded rect: 14x14, corner radius 3
  │ │      │ │       "H" in system bold, 10pt
  │ └──────┘ │       Dot: 5x5, positioned at (12, 12)
  │        ● │
  └──────────┘
```

## State Machine

The icon has exactly four visual states. These map to a strict priority hierarchy — the highest-priority applicable state wins.

```
                    ┌──────────┐
                    │  STOPPED │  gray, template
                    └────┬─────┘
                         │ server starts
                         ▼
                    ┌──────────┐
              ┌─────│  RUNNING │  green dot
              │     └────┬─────┘
              │          │ observer_count > 0
              │          ▼
              │     ┌──────────┐
              │     │ VIEWING  │  red dot (+ badge)
              │     └────┬─────┘
              │          │ observer_count == 0
              │          ▼
              │     back to RUNNING
              │
              │  (at any time, if problem detected)
              │          │
              │          ▼
              │     ┌──────────┐
              └────►│ ATTENTION│  yellow dot
                    └──────────┘
```

### State Definitions

| State | Dot color | Template? | Trigger | Priority |
|-------|-----------|-----------|---------|----------|
| **STOPPED** | None | Yes (adapts to light/dark) | Server process not running, port not in use | 4 (lowest) |
| **RUNNING** | Green (#22c55e) | No | Server responding to `/api/hash`, `observer_count == 0` | 3 |
| **VIEWING** | Red (#ef4444) | No | `observer_count > 0` | 1 (highest) |
| **ATTENTION** | Yellow (#eab308) | No | Missing permissions, server error, crash, not responding | 2 |

Priority rules:
- VIEWING always wins over RUNNING (someone is watching — this must be visible)
- ATTENTION wins over RUNNING but NOT over VIEWING (a permission warning shouldn't hide the fact that someone is watching)
- VIEWING + ATTENTION simultaneously: show VIEWING (red dot). The attention detail is in the menu.

### Transition Events

| From | To | Trigger |
|------|----|---------|
| STOPPED → RUNNING | `/api/hash` responds 200 for the first time |
| RUNNING → VIEWING | `observer_count` transitions from 0 to >0 |
| VIEWING → RUNNING | `observer_count` transitions from >0 to 0 |
| RUNNING → STOPPED | Server process exits or port no longer in use |
| VIEWING → STOPPED | Server dies while viewers connected (abrupt) |
| Any → ATTENTION | Permission check fails, server returns 5xx, poll timeout >3 cycles |
| ATTENTION → RUNNING | Problem resolved (permissions granted, server recovers) |

## Badge (Viewer Count)

When in the VIEWING state and `observer_count > 1`, a small number badge appears next to the red dot:

```
  ┌──────────┐
  │ ┌──────┐ │
  │ │  H   │ │        Single viewer: just a red dot
  │ └──────┘ │
  │        ● │
  └──────────┘

  ┌──────────┐
  │ ┌──────┐ │
  │ │  H   │3│        3 viewers: red dot + "3" text
  │ └──────┘ │        Number drawn in 7pt bold white on red circle
  │        ● │
  └──────────┘
```

For `observer_count == 1`, no number is shown — the red dot alone is sufficient. For counts 2-9, a single digit is drawn. For 10+, "9+" is shown (more than 9 simultaneous viewers is unusual).

Implementation: the badge replaces the simple dot with a larger red circle (7x7 points) containing centered white text.

## Template vs Non-Template

macOS menu bar icons use "template images" — monochrome images where macOS controls the fill color to match the current appearance (dark menu bar → white fill, light menu bar → dark fill).

- **STOPPED state**: template image. The icon is a neutral part of the menu bar.
- **All other states**: non-template image. The colored dot must render exactly as specified regardless of menu bar appearance.

When drawing the non-template version, the "H" and rounded rect are drawn in a fixed color that works on both light and dark menu bars:
- Light menu bar: `#1a1a2e` (near-black)
- Dark menu bar: `#e8e8f0` (near-white)

Detection: `NSAppearance.currentDrawingAppearance().name()` tells us if the menu bar is currently light or dark. The icon is redrawn when the appearance changes (observed via `NSApp.addObserver` for effective appearance).

## Appearance Change Handling

macOS can switch between light and dark mode at any time (manually or on schedule). The icon must update:

```python
# Register for appearance changes
NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
    self,
    "appearanceChanged:",
    "AppleInterfaceThemeChangedNotification",
    None,
)

def appearanceChanged_(self, notification):
    # Redraw icon with current appearance
    self._redraw_icon()
```

## Accessibility

- The status item button has a `toolTip` that describes the current state: "openhort — Server Running, 2 viewers connected" or "openhort — Server Stopped".
- VoiceOver reads the tooltip when the user navigates to the menu bar item.
- The tooltip updates on every status change.
- Menu items use standard NSMenuItem text — fully accessible to VoiceOver by default.

## Icon Rendering Implementation

The icon is drawn using `NSImage.lockFocus()` / `unlockFocus()` with `NSBezierPath` and `NSAttributedString`. No external image files.

Key considerations:
- Always draw at 18x18 **points** — macOS handles @2x scaling automatically when the image's `size` is set in points
- Use `NSFont.systemFontOfSize_weight_` for the "H" — matches the system font on all macOS versions
- Use `NSColor.labelColor()` in template mode (automatically adapts)
- Use fixed `NSColor` values in non-template mode (must look correct on both menu bar appearances)
- Call `setTemplate_(True)` only for the STOPPED state icon

## Retina Rendering

`NSImage.lockFocus()` draws at @1x by default. For crisp @2x rendering:

```python
image = NSImage.alloc().initWithSize_(NSMakeSize(18, 18))

# Create a representation that covers @2x
rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, 36, 36, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0
)
rep.setSize_(NSMakeSize(18, 18))  # points, not pixels

image.addRepresentation_(rep)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(
    NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
)
# ... draw at 36x36 pixels, macOS maps to 18x18 points ...
NSGraphicsContext.restoreGraphicsState()
```

This produces a crisp icon on Retina displays. On non-Retina (increasingly rare), macOS downscales automatically.

## Future: SF Symbols

macOS 11+ provides SF Symbols — Apple's icon font with thousands of glyphs. A future enhancement could use `NSImage(systemSymbolName:accessibilityDescription:)` for a more native feel, with the colored dot as a badge modifier. However, SF Symbols require the process to be a proper app bundle or use private API for CLI processes. The current programmatic approach works universally.
