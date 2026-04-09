# New UI Concept — Widget Home Screen

!!! note "Status: Design Phase"
    This document describes the target UI architecture for the openhort redesign. The [interactive mockup](../../../mockup-ui-rebuild.html) demonstrates all concepts described here. The current production UI (`index.html`) still uses the old flat-grid panel model.

## Why Rebuild the UI

The driving force behind the redesign is **data flow visibility**. When AI agents, terminals, and tools share a screen — some handling confidential data, some sandboxed, some public — users need to see at a glance which components can exchange data and which are isolated. The old UI provides no visual indication of security boundaries; the new UI encodes them into every layer of the interface through color.

Beyond security, the current UI is a **flat panel grid** — windows, terminals, and plugins all appear as equal cards in one scrollable list. This worked for a single machine with a handful of panels, but breaks down as openhort grows:

| Problem | Old UI | New UI |
|---------|--------|--------|
| **No spatial organization** | All panels in one flat list | Multiple desktops, each with a purpose |
| **No security visibility** | No indication which data zone a panel belongs to | Colored hort groups with visible boundaries |
| **No widget flexibility** | Every card is the same fixed size | 4 size options (1×1, 2×1, 1×2, 2×2), resizable |
| **Single device only** | One target's panels at a time, target bar at top | Multi-device hierarchy (pull-down device view) |
| **No customization** | Grid order determined by server | User arranges widgets freely across desktops |
| **Static thumbnails** | Screenshot + title, all identical | Live canvas rendering, sparklines, inline chat |

The new UI reimagines openhort as a **smartphone-style widget home screen** — think iOS/Android home screen meets security dashboard.

---

## Core Metaphor: Desktops, Not Lists

```mermaid
flowchart LR
    subgraph Hierarchy ["Spatial Hierarchy"]
        direction TB
        D[Devices] -->|pull down| DK[Desktops]
        DK -->|swipe| W[Widgets]
    end
```

Three zoom levels, each with a natural gesture:

| Level | What you see | Enter | Exit |
|-------|-------------|-------|------|
| **Widgets** | One desktop's widget grid | Default view | — |
| **Desktops** | All desktops as miniature cards | Long-press page dots | Click desktop / Escape |
| **Devices** | All connected targets | Pull down from top | Click device / back |

---

## Multiple Desktops

The central organizing concept. Instead of one flat list, widgets live on **named desktops** that the user swipes between horizontally.

### Home Desktop (Desktop 0)

Always exists. Cannot be deleted or renamed. Its widgets are **auto-populated** from live state:

- Active terminals (Claude sessions, shells)
- Extensions with `autoShow` enabled
- Pinned llmings

Sorted by favorites first, then last interaction time. Home desktop widgets are **not persisted** — they're computed fresh on every load.

### User Desktops

Created by the user for specific purposes. Examples from the mockup:

- **SAP Finance** — widgets scoped to the SAP security zone (red hort group)
- **HR Dashboard** — widgets for HR systems (purple hort group)
- **DevOps** — terminals and monitors for infrastructure

User desktops persist their widget list in localStorage, keyed by device class:

```
hort-layouts-phone
hort-layouts-tablet
hort-layouts-desktop
```

Each device class gets its own layout because a 2-column phone grid looks different from a 4-column desktop grid.

### Desktop Colors (Tints)

Every desktop has a **color tint** that subtly shifts the entire background palette. 16 colors available:

| Tint | RGB Base | Use Case |
|------|----------|----------|
| Blue (default) | `20, 40, 70` | General purpose |
| Crimson | `50, 16, 20` | High-security zones (SAP, finance) |
| Green | `16, 42, 24` | Public/open data |
| Purple | `35, 18, 50` | HR, PII-sensitive |
| Amber | `45, 35, 16` | Sandboxed environments |
| Teal | `16, 42, 42` | Monitoring dashboards |
| ... | ... | 10 more tints available |

The tint affects three things:

1. **Background plasma blobs** — the animated gradient blobs shift to match the desktop color
2. **Color field canvas** — a per-pixel blended background behind the grid, computed from widget positions and their hort group colors
3. **Widget border defaults** — ungrouped widgets inherit the desktop's tint for their subtle breathing border animation

Set via right-click on empty grid area → "Desktop Color" swatch picker.

### Desktop Navigation

- **Horizontal swipe** — content follows finger in real-time, rubber-band at edges, snaps on release (20% threshold)
- **Arrow keys** Left/Right
- **Trackpad horizontal scroll** (with cooldown to prevent over-scrolling)
- **Page dots** at bottom — click snaps to nearest desktop (44px invisible tap targets)
- **Desktop overview** — long-press the dot bar for full overview

### Page Dots

Always visible at the bottom inside a frosted pill (`backdrop-filter: blur(8px)`). Home desktop's dot is slightly squared (3px border-radius vs round). Active dot is blue and scaled up.

Long-press the dot bar → radial circle animation at touch point → opens desktop overview after 400ms.

---

## Desktop Overview

Full-screen overlay showing all desktops side-by-side as miniature cards.

```
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌ ─ ─ ─ ─ ┐
│  Home   │  │   SAP   │  │   HR    │  │    +    │
│ ░░░░░░░ │  │ ░░░░░░░ │  │         │  │  New    │
│ ░░░░░░░ │  │ ░░░░░░░ │  │ (empty) │  │ Desktop │
└─────────┘  └─────────┘  └─────────┘  └ ─ ─ ─ ─ ┘
   Home        SAP Finance   HR Dash       + New
```

Each card shows **real shrunken content** — rendered at viewport size and CSS-scaled down with `transform: scale()`. Active desktop highlighted with blue border. Widget animations are disabled inside overview cards for performance.

The "New Desktop" card has a dashed border and `+` icon. Click to create, or drag a widget onto it to create and move in one action.

---

## Device View

Triggered by **pulling down** when already at the top of the page, or by scrolling up past the top.

Shows all connected targets (MacBook, Docker Linux, Raspberry Pi, NAS, etc.) as full-sized cards with:

- Device icon (laptop, server, CPU, etc.)
- Device name
- Connection status (green dot = connected, grey = offline)
- Desktop count per device

Offline devices are greyed out (45% opacity) and not clickable.

```mermaid
flowchart TB
    subgraph DevView ["Device View"]
        MB["💻 MacBook Pro<br/>2 desktops — Connected"]
        DL["🐧 Docker Linux<br/>1 desktop — Online"]
        PI["🔲 Raspberry Pi<br/>1 desktop — Online"]
        MM["🖥 Mac Mini Server<br/>3 desktops — Offline"]
    end
```

---

## Widget System

### Sizes

Widgets span CSS grid cells in 4 combinations:

| Size | Columns × Rows | Use Case |
|------|----------------|----------|
| `1×1` | 1 col, 1 row | Compact: clock, stats, single window |
| `2×1` | 2 cols, 1 row | Wide: desktop preview, chat, filters |
| `1×2` | 1 col, 2 rows | Tall: Claude terminal, code sessions |
| `2×2` | 2 cols, 2 rows | Large: full dashboards |

### Responsive Grid

Columns are computed dynamically based on viewport width:

```
cols = max(2, floor((viewportWidth - 2×padding + gap) / (cellWidth + gap)))
```

With `cellWidth = 280px`, `gap = 14px`, `padding = 20px`:

| Screen | Columns | Row Height |
|--------|---------|------------|
| Phone portrait | 2 | 180px |
| Phone landscape / small tablet (≥640px) | 3 | 190px |
| Desktop (≥1024px) | 4 | 190px |
| Large desktop | 5+ | 190px |

Grid is centered with `max-width: 1200px` and `justify-content: center`.

### Widget Types

| Type | Default Size | Content |
|------|-------------|---------|
| `terminal` | 1×1 (1×2 for Claude) | Monospace output, state indicator (thinking/idle), idle timer |
| `extension` | 1×1 | Canvas thumbnail with live data (sparklines, gauges, counters) |
| `extension-sub` | 1×1 | Sub-element of a llming: individual window, sensor, room |
| `quick-chat` | 2×1 | Inline chat with message bubbles + input field |
| `clock` | 1×1 | Time display + uptime counter |

### Widget Visual Design

Every widget card has:

- **Background:** `#111827` (surface color)
- **Border:** 1px solid, with a **6-second breathing animation** — the border subtly brightens and fades
- **Border radius:** 14px
- **Hover:** animation pauses, outer glow appears (`box-shadow: 0 0 25px`), border brightens
- **Label bar** at bottom with icon + title
- **Press feedback:** `transform: scale(0.97)` on click/tap

The border color and glow color change based on the widget's **hort group assignment** (see below).

### Centered Coordinate System

Widget positions use a **centered coordinate system** where column 0 is the center of the screen. This means widgets maintain their relative position to the center regardless of how many columns the screen can display. On a 2-column phone, the grid contracts around center; on a 4-column desktop, it expands — but widgets stay spatially consistent.

The `colOffset` (half the column count) maps between centered coordinates and CSS grid column numbers.

---

## Hort Groups — The Reason for the Redesign

The entire color system exists for one purpose: **making data flow boundaries visible so users can verify isolation at a glance**.

When multiple AI agents, terminals, and tools share a screen — some with access to confidential SAP data, some sandboxed, some on the public internet — the critical question is always: *which of these can talk to each other, and where is my data allowed to flow?*

In the old UI, this is invisible. The MCP bridge enforces isolation in the backend, but the user has no way to see it. You have to trust the configuration. The new UI solves this by encoding security zones into color — every pixel of the interface tells you what zone you're looking at.

### What Are Hort Groups?

Each hort group represents a **data flow boundary** — a set of permissions, network restrictions, and information flow policies. Defined in `hort-config.yaml`, enforced by the MCP bridge (see [Wiring Model](../security/wiring-model.md)). The new UI makes these boundaries **visible** through color so you can answer "can this widget see that widget's data?" without reading config files.

### The Five Default Groups

| Group | Color | Tint | Icon | Description |
|-------|-------|------|------|-------------|
| **Local** | Blue `#3b82f6` | Blue | `ph-house` | Local machine, no restrictions |
| **Sandboxed** | Amber `#f59e0b` | Amber | `ph-shield-warning` | Container-isolated, limited network |
| **SAP Finance** | Red `#ef4444` | Crimson | `ph-lock` | Confidential — no network out, no email |
| **Public** | Green `#22c55e` | Green | `ph-globe` | Public data only, unrestricted output |
| **HR Systems** | Purple `#a855f7` | Purple | `ph-users` | PII — no logging, no external sharing |

### How Groups Appear in the UI

Hort groups manifest in three visual layers:

#### 1. Widget Border Color

Widgets assigned to a hort group get that group's color as their border. The breathing animation uses the group's tint RGB values for the glow. Ungrouped widgets use the desktop's default tint.

```css
/* Grouped widget: amber border with amber glow */
border-color: #f59e0b99;
--rest-glow: 0 0 30px rgba(180, 140, 64, 0.45);
--hover-glow: #f59e0b;

/* Ungrouped widget: inherits desktop tint */
border-color: #1a3050;
--rest-glow: 0 0 30px rgba(80, 160, 280, 0.4);
```

#### 2. Color Field Background

Behind the widget grid, a `<canvas>` renders a per-pixel distance-weighted color field. Each widget's position projects its hort group's color onto a low-resolution canvas (160px wide), with soft rounded-rect gradients and glow layers. The result is a subtle, organic background that shifts color based on what security zones are present on the desktop.

The canvas is re-rendered whenever:

- Widget hort assignments change
- Desktop tint changes
- Active desktop switches
- Window resizes

Screen edges blend to near-black (`rgb(4, 6, 12)`) for a natural vignette effect.

#### 3. Connection Dots in Widget Labels

Widgets that bridge multiple hort groups (e.g., a chat widget connected to both Sandboxed and SAP) show small colored dots in their label bar — one per connected group. This makes cross-zone data flows visible.

```
┌──────────────────────────┐
│  [chat messages]         │
│  ...                     │
│  💬 Chat    🟡 🔴        │  ← dots show Sandboxed (amber) + SAP (red)
└──────────────────────────┘
```

### Assigning Hort Groups

Right-click a widget → the context menu shows a "Hort" section listing all available groups. Select one to assign, or "None" to clear.

Desktops can also have a **default hort group** — all widgets on that desktop inherit it unless individually overridden. The SAP Finance desktop, for example, defaults all its widgets to the `sap` group.

### Reading the Screen — A Worked Example

Consider the Home desktop in the mockup. Without opening any settings or reading any config:

1. **The Claude terminal glows amber** — it's running in the Sandboxed zone. It can access local files but can't reach the internet or SAP systems.
2. **The System Monitor also glows amber** — it shares data with Claude (same zone). Claude can read CPU metrics.
3. **The Desktop preview has no colored border** — it's ungrouped, inheriting the desktop's default blue. It's local-only.
4. **The Chat widget has two dots: amber + red** — it bridges the Sandboxed and SAP zones. This is a deliberate cross-zone connection. Data typed here could reach both zones. This is the kind of thing that deserves visual attention.
5. **The Network and Clipboard widgets glow green** — Public zone. Their data can flow anywhere, which is fine because it's not sensitive.
6. **The entire background subtly shifts** from amber (where the sandboxed widgets are) to green (where the public widgets are), with blue in between. The color field makes zone clusters visible even at a distance.

Now swipe to the SAP Finance desktop:

- **Everything is red.** Every widget — terminal, chat, metrics — is in the SAP zone. The background is crimson. You can see in an instant that this is a sealed environment. No data leaves.
- **If someone accidentally added a Public widget here**, it would glow green against the red background — an immediate visual anomaly that says "this doesn't belong."

This is the core value proposition: **security boundaries you can see, not just trust.**

---

## Adding Widgets

Three entry points, each optimized for a different speed:

### 1. Navbar `+` Button

Small dashed-border button in the top bar. Opens a popover:

- **Spawn Claude** — new Claude Code terminal (1×2, purple icon)
- **New Terminal** — shell session (1×1)
- **Add Screen** — opens window picker
- **Widget Catalog** — opens full bottom-sheet picker

### 2. Right-Click / Long-Press Empty Area

Context menu at cursor position with:

- **Widget Catalog** (top item, bold, blue)
- Spawn Claude, New Terminal, Add Screen
- **Recent** — last 4 widget types added (builds up with use)
- **Desktop Color** — 16 tint swatches
- **Edit layout** — enters edit mode

### 3. Ghost Card

A subtle floating `+` button (40×40px, dashed border) pinned to the bottom-right corner. 20% opacity, scales up on hover. Hidden in edit mode.

### Widget Catalog (Full Picker)

Bottom-sheet modal (phone) or centered modal (desktop) with search bar. Three categories:

- **Quick Actions** — Spawn Claude, New Terminal
- **Llmings** — each with drill-down for sub-widgets (caret `>` indicator). E.g., System Monitor → CPU Chart, Memory, Disk, Temperature
- **Built-in** — Quick Chat, Clock

### Llming Lens Flow

Special multi-step flow for adding screen capture widgets:

```mermaid
flowchart TD
    A[Llming Lens] --> B[Full Desktop]
    A --> C[Screen]
    A --> D[Select Windows]
    A --> E[Window Filter]
    
    C --> C1[Choose display]
    D --> D1[Searchable checkbox list<br/>+ size selector<br/>'Add N widgets' button]
    E --> E1[Type filter terms as tags<br/>Live preview of matches<br/>Size selector<br/>'Add filter widget' button]
```

The **Window Filter** is particularly powerful: type multiple terms as tags (e.g., "Teams" + "Slack"), see a live preview of matching windows, and create a dynamic widget that auto-shows matching windows as they appear.

---

## Edit Mode

### Entering Edit Mode

- Long-press any widget (500ms, cancels if moved >8px)
- Right-click empty area → "Edit layout"

### Visual Feedback

All widgets wiggle (`animation: wiggle 0.25s infinite alternate`). Delete badges (×) appear top-left. Size labels appear bottom-right (e.g., "1×2").

### Resize

Drag handles appear on the right and bottom edges of each widget:

- **Right edge** → widen/narrow (toggles between 1 and 2 columns)
- **Bottom edge** → heighten/shorten (toggles between 1 and 2 rows)

30px drag threshold to commit the resize.

### Drag-and-Drop

Widgets are draggable in edit mode. A **grid-aligned ghost** (dashed blue border) shows where the widget will land. The ghost uses CSS grid placement for pixel-perfect alignment. Red ghost = overlap detected, drop rejected.

### Bottom Bar in Edit Mode

The bottom bar splits into two zones:

```
┌─────────────────────────────────┬──────────┐
│  🔵 Move to desktop (80%)       │  🔴 🗑  │
│  (drag here → desktop overview)  │  (20%)  │
└─────────────────────────────────┴──────────┘
```

- **Blue zone (left 80%)** — drag a widget here to open the desktop overview and drop onto any desktop
- **Red zone (right 20%)** — drag here to delete

---

## Background Visual Effects

### Plasma Blobs

Three independent CSS gradient blobs behind the grid, animated with different speeds:

| Blob | Size | Speed | Motion |
|------|------|-------|--------|
| `::before` | 70% | 12s | Drift + scale (1.0–1.1) |
| `::after` | 60% | 16s | Counter-drift + scale (0.95–1.08) |
| `.plasma-blob::before` | 50% | 20s | Drift + scale + rotate (±5°) |

All blobs use `filter: blur(50-60px)` for a soft, ambient effect. Colors come from the desktop tint's CSS custom properties (`--plasma1`, `--plasma2`, `--plasma3`).

### Color Field Canvas

A `<canvas>` element positioned behind the grid on each desktop page. Renders at 160px wide (low resolution) and stretched to fill, creating a naturally blurred effect. Algorithm:

1. Fill with near-black border color
2. For each widget, project a soft rounded rect at the widget's position using its hort group's RGB values
3. Apply multiple glow layers (5 levels, exponential falloff) for soft edges
4. Solid core in the center

The canvas re-renders on widget changes, desktop switches, and window resizes.

---

## Navbar

Minimal: `[☰] [OpenHORT] [Desktop name] [spacer] [Lemming] [+] [Viewers]`

| Element | Behavior |
|---------|----------|
| **Hamburger** | Opens nav drawer |
| **OpenHORT** | Logo, gold `#e8b930`, 17px italic bold |
| **Desktop name** | Click to rename (user desktops only) |
| **Lemming icon** | Connection indicator: gold (nobody), blue (LAN), red (external) |
| **`+` button** | Dashed border, opens quick add popover |
| **Viewer count** | Badge showing connected users |

## Nav Drawer

Deliberately minimal — only things that don't belong on the desktop itself:

- **Horts** — bold, navigates to Home desktop
- **Search** — universal search across llmings, windows, and actions (with type labels in results)
- **Settings** — opens settings (includes logout)
- **Help** — documentation links

No llming list (use Widget Catalog), no desktop list (use dots), no connector list, no quick actions (use `+` button).

---

## Widget Data Model

```javascript
{
  id: 'w_abc123',           // unique widget ID
  type: 'terminal',         // terminal | extension | extension-sub | quick-chat | clock
  extId: 'system-monitor',  // extension ID (null for terminals)
  subId: 'tmux:claude',     // sub-element ID
  size: '1x1',              // grid span: 1x1, 2x1, 1x2, 2x2
  order: 0,                 // sort position (for auto-flow)
  pos: {c: -1, r: 0, w: 1, h: 2},  // centered grid position (optional)
  hpiort: 'sandboxed',      // hort group assignment (null = inherit desktop default)
  hortConnections: ['sandboxed', 'sap'],  // cross-zone bridges (shown as dots)
  config: {},               // widget-specific configuration
  c: {                      // display config
    title: 'System',
    iconClass: 'ph ph-chart-line-up',
    iconColor: 'var(--purple)',
    state: 'thinking',      // terminal state
    idle: 12,               // idle seconds
    output: '$ ...'         // terminal output preview
  }
}
```

---

## Gesture Reference

| Gesture | Context | Effect |
|---------|---------|--------|
| **Swipe left/right** | Viewport | Switch desktop (12px lock threshold, 20% commit threshold) |
| **Pull down** | At top of page | Open device view (80px threshold, 40% damping) |
| **Scroll wheel up** | At top | Instant device view trigger (`deltaY < -30`) |
| **Horizontal scroll wheel** | Viewport | Switch desktop (20px threshold, 300ms cooldown) |
| **Tap widget** | Widget | Select (first tap), open (second tap) |
| **Long-press widget** | Widget (500ms) | Enter edit mode |
| **Long-press empty area** | Grid (500ms) | Open context menu |
| **Long-press page dots** | Dot bar (400ms) | Open desktop overview (with radial circle animation) |
| **Right-click widget** | Widget | Hort group assignment + remove |
| **Right-click empty area** | Grid | Widget catalog + desktop color + edit layout |
| **Drag widget** | Edit mode | Reorder / move to desktop / trash |
| **Drag right edge** | Edit mode | Resize width (1↔2 columns) |
| **Drag bottom edge** | Edit mode | Resize height (1↔2 rows) |

---

## Comparison: Old vs New

```mermaid
flowchart LR
    subgraph Old ["Current UI"]
        direction TB
        O1[Flat panel grid]
        O2[Fixed card sizes]
        O3[Target bar filter]
        O4[No security visualization]
        O5[Server-determined order]
    end
    subgraph New ["New UI"]
        direction TB
        N1[Multi-desktop home screen]
        N2[4 widget sizes, resizable]
        N3[Pull-down device view]
        N4[Hort groups with colored boundaries]
        N5[User-arranged, persistent layouts]
    end
    Old -.->|"redesign"| New
```

| Aspect | Current UI | New UI |
|--------|-----------|--------|
| **Layout** | Single scrollable grid | Multiple swipeable desktops |
| **Card sizes** | Fixed (all same) | 1×1, 2×1, 1×2, 2×2, user-resizable |
| **Device switching** | Target bar at top | Full-screen device view (pull-down) |
| **Security** | Invisible | Colored hort groups, border glow, connection dots, color field background |
| **Organization** | Server order, group filter | User-arranged, per-desktop, drag-and-drop |
| **Adding panels** | `+` button → dialog | 3 entry points: navbar `+`, context menu, ghost card, widget catalog with drill-down |
| **Background** | Flat dark | Animated plasma blobs + per-desktop color tint + per-widget color field |
| **Edit mode** | None | Wiggle, resize handles, drag-to-reorder, desktop overview drop zones |
| **Persistence** | None (server state) | localStorage per device class (phone/tablet/desktop) |
| **Widget content** | Screenshot thumbnail | Live sparklines, inline chat, state indicators, canvas rendering |
