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

### Widget Drag & Drop

Drag is pointer-based (not HTML5 drag API) — this allows seamless transition from long-press into drag without releasing the mouse button.

**Initiating a drag:**

- **Not in edit mode:** Long-press a widget (500ms) → edit mode enters → drag starts immediately on the same pointer hold. No re-click needed.
- **Already in edit mode:** Pointerdown on any widget → drag starts immediately.

**During drag:**

- The widget element becomes `position: fixed` and follows the cursor at the exact grab point offset (where within the widget you pressed).
- A **ghost overlay** shows the target grid cell using CSS grid placement.
- Ghost is **blue** when the target cell is free, **red** when it collides with another widget.

**On drop:**

- **No collision:** Widget moves to the target cell. New center-relative position is persisted to IndexedDB.
- **Collision:** Widget snaps back to its original position. Nothing is persisted — it could have been an accident.

**Swipe prevention:** When the pointer is on a widget, desktop swiping is disabled. Swiping only works from empty grid areas or the viewport edges.

## Widget Interactions

| Action | Desktop | Mobile | Effect |
|--------|---------|--------|--------|
| Hover | Mouse over | — | Outer blue glow, no border change |
| Click/Tap | Click | Tap | Opens the widget (terminal, extension, etc.) |
| Right-click | Right-click | — | Size/remove context menu |
| Long-press | 500ms hold | 500ms hold | Enter edit mode + start drag in one gesture |
| Drag (edit mode) | Pointerdown + move | Touch + move | Move widget to new grid position |
| Drag edges | In edit mode | In edit mode | Resize (right edge = width, bottom edge = height) |
| Drop on empty | Release | Release | Widget placed, position persisted |
| Drop on occupied | Release | Release | Widget snaps back, nothing persisted |
| Open app | Click widget | Tap widget | Opens float window or fullscreen |
| Close app | Escape / Back / click outside | Back / tap outside | Closes topmost app |

### App Window Lifecycle

When a widget is clicked, its app opens as a float window (desktop) or fullscreen panel (mobile).

**Opening:** `history.pushState()` adds a browser history entry with the app name in the URL (`?app=now-playing`). This enables:

- **Browser back button** closes the app (via `popstate` listener)
- **Escape key** closes the topmost float window
- **Click outside** the float window (on the dark backdrop) closes it
- **URL sharing** — the `?app=` parameter identifies the open app

**Closing priority** (Escape / Back): float windows first (topmost), then fullscreen spirit, then overlays (device view, desktop overview, picker, drawer, menus).

**Backdrop:** A semi-transparent dark overlay (`rgba(0,0,0,.3)`) appears behind float windows. Click it to close. The float window itself has `@click.stop` to prevent close on internal clicks.

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

Widget layouts are a **client-side decision**, stored in IndexedDB keyed by device class. This allows completely independent layouts on phone, tablet, and desktop — same server, different presentations.

**Database:** `hort-widget-layout`, store `layouts`.

**Keys:** `phone` | `tablet` | `desktop` (from `LlmingClient.getDeviceType()`).

**What's stored:** The complete desktops array including widget positions, sizes, hort assignments, and ordering. Server decides which llmings *exist*; client decides *where* they appear.

**Default presets:** On first load (no saved layout), 4 desktops are created matching the reference mockup: Home (15 widgets), SAP Finance (3 widgets), HR Dashboard (empty), Smart Home (5 widgets). These presets include hort group assignments (sandboxed, public, sap) for demonstrating security boundary visualization.

**Save trigger:** Debounced 2-second save on any widget/desktop change via `whScheduleSave()`.

### Widget Data Model

```javascript
{
  id: 'w_101',
  type: 'terminal' | 'extension' | 'quick-chat',
  extId: 'system-monitor',    // extension ID (null for terminals)
  subId: 'claude_dev',        // terminal name (null for extensions)
  size: '1x1',                // grid span: 1x1, 2x1, 1x2, 2x2
  hpiort: 'sandboxed',        // hort group assignment (null = inherit from desktop)
  hortConnections: [],         // multi-hort bridges (for chat widgets)
  pos: { c: -1, r: 0 },      // center-relative grid position (see below)
  c: {                        // display config
    title: 'System Monitor',
    iconClass: 'ph ph-cpu',
  }
}
```

### Center-Relative Positioning

Every widget has an absolute position in the grid, expressed as **center-relative coordinates**:

```
pos: { c: -2, r: 0 }   // 2 columns left of center, row 0
pos: { c: 0, r: 1 }    // center column, row 1
pos: { c: 1, r: 3 }    // 1 column right of center, row 3
```

The center of the screen is `c=0`. This means:
- When the user resizes the browser **horizontally**, widgets stay anchored to the center — columns are added/removed at the edges, not in the middle.
- When the user resizes **vertically**, nothing changes — vertical scroll handles overflow.

**Column offset:** At runtime, the grid has `N` columns. Column index 0 in CSS grid maps to center-relative `c = -(N/2)`. The display function maps `pos.c` → CSS grid column via `gridColumn = pos.c + floor(N/2) + 1`.

### Responsive Reflow (Temporary Positions)

When the column count changes drastically (e.g., portrait → landscape rotation), stored positions may not fit the new grid. The system handles this with **temporary positions**:

1. **Column count changes** → `whComputePositions()` runs.
2. For each widget, try to place it at its stored `pos`. If the position fits (within column bounds, no overlap), use it.
3. If the position doesn't fit, **auto-reflow**: place the widget in the next available cell, preserving the original ordering.
4. These reflowed positions are **temporary** — they are NOT persisted to IndexedDB. If the user rotates back, the original positions are restored from the saved layout.
5. **However**, if the user manually drags ANY widget in the reflowed layout, ALL current positions (including temporary ones) are persisted as the new canonical layout for this device class. This "commits" the temporary layout.

This means:
- Quick orientation changes are non-destructive — rotate and rotate back, everything returns to where it was.
- Intentional rearrangement in a new orientation is respected — one manual drag commits the whole layout.

### Foldable Support (Samsung ZFold)

Inner display (700-820px) gets 3 columns. Unfolded landscape gets 4+. The center-relative coordinate system ensures widgets stay centered across these transitions.

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
