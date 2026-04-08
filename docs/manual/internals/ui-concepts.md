# UI Concepts — Widget Home Screen

The OpenHORT UI is a smartphone-style widget home screen with multiple desktops, optimized for everything from iPhones to Samsung ZFold to desktop monitors.

## Spatial Hierarchy

Three zoom levels, navigated naturally:

```
Devices → Desktops → Widgets
```

| Level | What you see | How to get there | How to leave |
|-------|-------------|------------------|--------------|
| **Widgets** | One desktop's widget grid | Default view | — |
| **Desktops** | All desktops as miniature cards | Long-press dots, or drag widget to bottom blue zone | Click a desktop, click outside, Escape |
| **Devices** | All connected targets as full cards | Pull down from top, or scroll wheel up at top | Click a device, back button, Escape |

### Widget View (default)

The main view. A responsive CSS grid of widgets filling the screen. Vertical scroll within a desktop, horizontal swipe between desktops.

### Desktop Overview

Triggered by long-press on the page dots. Shows all desktops side-by-side as miniature cards with **real shrunken content** (not placeholders) — rendered at viewport size and scaled down with `transform: scale()`. Active desktop highlighted with blue border.

Also triggered in edit mode when dragging a widget toward the bottom "Move to desktop" zone — opens the overview so you can drop the widget on any desktop or create a new one.

### Device View

Full-screen view of all connected targets (MacBook, Docker Linux, Raspberry Pi, NAS, etc.). Each device is a full-sized card with icon, name, and connection status. Triggered by:

- **Pull down** when already at the top of the page (rubber-band feel)
- **Scroll wheel up** past the top
- **"All devices" link** in desktop overview

Offline devices are greyed out and not clickable.

## Grid System

### Responsive Columns

| Screen | Columns | Row Height |
|--------|---------|-----------|
| Phone portrait (default) | 2 | 180px |
| Phone landscape / small tablet (≥640px) | 3 | 200px |
| Tablet portrait (≥768px) | 3 | 210px |
| Desktop (≥1024px) | 4 | 190px |
| Large desktop (≥1440px) | 4 | 210px |
| ZFold inner (700-820px) | 3 | — |

Grid is centered with `max-width: 1200px` on desktop.

### Widget Sizes

Widgets span grid cells in 4 combinations:

| Size | Columns × Rows | Use case |
|------|----------------|----------|
| `1×1` | Half width, half height | Compact: clock, stats |
| `2×1` | Full width, half height | Wide: desktop preview, chat |
| `1×2` | Half width, full height | Tall: Claude terminal |
| `2×2` | Full width, full height | Large: dashboards |

### Resizing

In **edit mode**: drag the right edge to widen/narrow, drag the bottom edge to heighten/shorten. Snaps to grid units (1 or 2). Size label shown in bottom-right corner during edit mode only.

Outside edit mode: no resize handles visible. Widgets glow on hover instead.

## Multiple Desktops

### Home Desktop

Desktop 0 is always "Home". Its widgets are **auto-populated** from live state — not persisted. Shows all active terminals, autoShow extensions, and pinned spirits. Sorted by favorites then last interaction.

### User Desktops

Created via "New Desktop" (from `+` menu or desktop overview). Widgets are explicitly added and persisted in localStorage per device class (phone/tablet/desktop).

### Navigation

- **Horizontal swipe** (touch or mouse drag) — content follows finger in real-time with rubber-band resistance at edges, snaps on release
- **Arrow keys** Left/Right
- **Trackpad horizontal scroll**
- **Page dots** — click anywhere in the dot bar, snaps to nearest desktop (large touch target with invisible 44px `::before` hit area)
- **Desktop overview** — click any desktop card

### Page Dots

Always visible at the bottom. Home desktop dot is slightly squared (3px border-radius). Active dot is blue and scaled up. The entire dot bar area is a long-press target for opening the desktop overview, with a radial circle feedback animation at the touch point.

## Widget Types

| Type | Default Size | Content |
|------|-------------|---------|
| `terminal` | 1×1 (1×2 for Claude) | Terminal output, state indicator (thinking/idle), idle timer |
| `extension` | 1×1 | Canvas thumbnail, icon, title. E.g., System Monitor, Network |
| `extension-sub` | 1×1 | Sub-element: individual window, filter, room, sensor |
| `quick-chat` | 2×1 | Last messages + input field |
| `clock` | 1×1 | Time + uptime |

## Adding Widgets

Three entry points, each optimized for a different speed:

### 1. Navbar `+` Button

Small dashed-border button in the top bar. Click → popover with:

- Spawn Claude
- New Terminal
- Add Screen (opens window picker)
- Widget Catalog (opens full picker)

### 2. Right-Click / Long-Press Empty Area

Compact context menu at cursor with:

- **Widget Catalog** (top item, bold)
- Spawn Claude, New Terminal, Add Screen
- **Recent** — last 4 widget types added (builds up with use)
- Edit layout

### 3. Ghost Card

Subtle dashed `+` card after the last widget in every grid. Click → opens full Widget Catalog.

### Widget Catalog (Full Picker)

Bottom-sheet modal with search bar. Categories:

- **Quick Actions** — Spawn Claude, New Terminal
- **Llmings** — each with drill-down for sub-widgets (arrow `>` indicator)
- **Built-in** — Quick Chat, Clock

### Llming Lens Flow

When adding Llming Lens, a custom multi-step flow:

1. **Choose type**: Full Desktop, Screen (if multiple displays), Select Windows, Window Filter
2. **Select Windows**: searchable checkbox list of all windows. Pick one or many. Size selector (1×1, 2×1, 1×2). "Add N widgets" button.
3. **Window Filter**: type multiple filter terms as tags (e.g., "Teams" + "Slack"). Live preview shows matching windows. Creates a dynamic widget that auto-shows matching windows.

### Screen Picker (Quick)

From the `+` menu → "Add Screen". Shows all current windows (VS Code, Chrome, Terminal, etc.) with app icons and colors. One tap to add as a 1×1 widget.

## Removing Widgets

### Edit Mode

Enter via right-click → "Edit layout", or long-press a widget. All widgets wiggle (`animation: wiggle .25s infinite alternate`). Delete badges (×) appear top-left of each widget. Size labels appear bottom-right.

**Bottom bar splits**: left 80% blue gradient ("Move to desktop"), right 20% red gradient (trash icon). Drag a widget to the blue zone → opens desktop overview for cross-desktop moves. Drag to red zone → delete.

### Right-Click Widget

Context menu with size options (1×1, 2×1, 1×2, 2×2) and "Remove" (red).

### Long-Press Cancellation

Any pointer movement >8px cancels a pending long-press. Prevents accidental edit mode when swiping.

## Widget Interactions

| Action | Desktop | Mobile | Effect |
|--------|---------|--------|--------|
| Hover | Mouse over | — | Outer blue glow, no border change |
| Click/Tap | Click | Tap | Opens the widget (terminal, extension, etc.) |
| Right-click | Right-click | — | Size/remove context menu |
| Long-press | — | 500ms hold | Enter edit mode |
| Drag edges | In edit mode | In edit mode | Resize (right edge = width, bottom edge = height) |

## Navbar

Minimal: `[☰] [OpenHORT] [Desktop name] [spacer] [Lemming icon] [+] [Viewers]`

- **Hamburger** — opens drawer
- **OpenHORT** — logo, bright gold (#e8b930), 17px italic
- **Desktop name** — click to rename (user desktops only)
- **Lemming icon** — connection security: gold (nobody), blue (LAN only), red (external access)
- **`+` button** — dashed border, opens quick add popover
- **Viewer count** — shows connected users

## Nav Drawer

Minimal — only things that don't belong on the desktop:

- **Horts** — top item, bold, navigates to Home desktop
- **Search** — universal search across llmings, windows, and actions. Results show type labels. When searching, all other sections hidden.
- **Settings** — opens settings (includes logout)
- **Help** — includes documentation

No llming list (use Widget Catalog), no desktop list (use dots), no connector list, no quick actions (use `+` button).

## Visual Design

### Background

Animated plasma effect — three independent gradient blobs with different sizes, positions, and animation speeds (12s/16s/20s). Each blob drifts, scales, and rotates independently. Blurred with `filter: blur(50-60px)`. Dark navy/blue tones. Pure CSS, zero JS overhead.

### Widget Cards

- Background: `var(--surface)` (#111827)
- Border: 1px solid, subtle breathing animation (6s cycle, border brightens and fades)
- Border radius: 14px
- Hover: animation pauses, outer blue glow (`box-shadow: 0 0 20px/40px`), border brightens
- Label bar at bottom with icon + title

### Theme Variables

```css
--bg: #0a0e1a        /* Dark background */
--surface: #111827   /* Card surfaces */
--border: #1e3a5f    /* Borders */
--primary: #3b82f6   /* Blue accent */
--accent: #60a5fa    /* Light blue */
--text: #f0f4ff      /* Main text */
--dim: #94a3b8       /* Subdued text */
--danger: #ef4444    /* Red */
--success: #22c55e   /* Green */
--purple: #a78bfa    /* Claude/AI accent */
```

### Terminal Text

Monospace (`SF Mono`, `Fira Code`), 10px, color `#c8d0dc` (brighter than dim).

## Layout Persistence

Layouts stored in localStorage keyed by device class:

```
hort-layouts-phone
hort-layouts-tablet
hort-layouts-desktop
```

Home desktop widgets are NOT stored (computed from live state). User desktops store their explicit widget lists. Debounced save on any change.

### Widget Data Model

```javascript
{
  id: 'w_abc123',
  type: 'terminal' | 'extension' | 'extension-sub' | 'quick-chat' | 'clock',
  extId: 'system-monitor',    // extension ID (null for terminals)
  subId: 'tmux:claude',       // sub-element ID
  size: '1x1',                // grid span
  order: 0,                   // sort position
  config: {}                  // widget-specific
}
```

## Responsive Behavior

### Orientation Change

CSS Grid reflows automatically via `--grid-cols` media queries. No JavaScript needed. Widgets maintain their span values.

### Foldable Support (Samsung ZFold)

Inner display (700-820px) gets 3 columns. Unfolded landscape gets 4 columns. Grid adapts via media queries targeting these width ranges.

### Desktop Centering

On screens ≥1024px, the grid is centered with `max-width` and `margin: 0 auto`. Prevents the "squeezed into top-left corner" look.

## Swipe & Gesture Details

### Desktop Swipe

Touch handlers attached to the viewport via JavaScript with `{passive: false}` to allow `preventDefault()` on horizontal swipes while letting vertical scroll pass through natively (`touch-action: pan-y` on pages).

- Horizontal movement >12px locks to swipe mode
- Vertical movement >10px locks to scroll mode (swipe ignored)
- Content follows finger in real-time (`transform: translateX()` updated every frame)
- Rubber-band resistance at first/last desktop edges (30% damping)
- Release threshold: 20% of viewport width to commit the swipe
- Smooth snap animation: `transform .25s cubic-bezier(.25,.1,.25,1)`

### Long-Press Detection

500ms hold without >8px movement. Uses `pointerdown` + `pointermove` listener that cancels the timeout if movement exceeds threshold. Prevents false triggers during swipe gestures.

### Pull-Down (Device View)

When page `scrollTop ≤ 2` and user drags/scrolls further up:

- Touch: 40% damping on pull distance, threshold 80px to trigger
- Mouse: same via mousedown + mousemove
- Scroll wheel: instant trigger on `deltaY < -30`

Visual indicator shows during pull: animated arrow that flips and turns blue when past threshold, "Release for devices" text.

## Context Menu Behavior

- Auto-closes when pointer moves >15px (prevents stale menus during accidental drags)
- Positioned at click point, clamped to viewport bounds
- Escape closes all menus
