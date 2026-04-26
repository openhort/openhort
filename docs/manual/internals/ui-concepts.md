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

### Built-in widget viewers

Some widgets aren't backed by a llming with a card.vue / app.vue — the home grid renders them inline using a fixed template. Today these are:

- **Terminal widget** (`type: 'terminal'`) — claude_dev, sap_agent, etc. Inline body shows the output stream + status row.
- **Quick-chat widget** (`type: 'quick-chat'`) — the demo "Turn on living room lights" panel.

Clicking such a widget opens a host-rendered float (no iframe — these aren't sandboxed). The float window template carries inline `<template v-if="fw.widgetName === '__builtin:terminal'">` / `__builtin:chat` blocks that render a larger version of the same content. The float has its own X button and obeys Esc / backdrop close like any other app, but it does NOT change the URL — these floats are ephemeral (live data, not deep-linkable).

If a real terminal backend is connected, the click goes through `openTerminal(subId)` instead and routes to the full PTY-backed terminal view.

### Deep-Link URL Parameters

The home grid honours three query params on initial load and on every history navigation (back/forward). They're applied **after** llming manifests are discovered, so the open-app target is always resolvable. Apply order is `desktop` → `app`.

| Param | Value | Behaviour |
|---|---|---|
| `desktop` | integer (0-based) | Switch to that desktop. Out-of-range values are clamped. |
| `app` | llming id (e.g. `weather`) | Open the named llming. Default mode = window for non-fullscreen-capable, fullscreen otherwise. |
| `mode` | `window` \| `fullscreen` \| `widget` | **window** = always a hovering float (overrides `fullscreenCapable`). **fullscreen** = always navigate to the full-screen llming view. **widget** = no-op for opening — caller wants the widget on the grid only (used by share links that already include the desktop). |

Examples:

- `/?desktop=2` — open the third desktop on load
- `/?app=weather` — open weather as a hovering window
- `/?app=llming-lens&mode=fullscreen` — force fullscreen even on desktop monitors
- `/?desktop=1&app=cameras&mode=window` — switch to desktop 1 and pop the cameras window
- `/?app=hort-chief&mode=widget` — equivalent to `/` (no float opens)

**Idempotency:** the parser tracks the last-applied `app|mode` key, so an already-open window is not re-opened on duplicate parses (back-button replays the same URL fires `popstate`, but no extra window appears).

**Llmings without a UI:** if a manifest exists but declares no `ui_widgets` and no `app.vue`, `openLlming` still opens a small placeholder float ("this llming has no UI yet") instead of failing silently. This matters for connector-only llmings like `claude-cli-ext` that the user might still try to open from a share link.

Implementation: `_applyHortUrlParams()` in `hort/static/index.html`, called from the `_hortOnConnect` callback after `HortPlugins.discoverAndLoadPlugins()` and on every `popstate`.

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

## Apps and Subapps

Two kinds of windowed UI exist on top of the widget grid. Both use the **same underlying float window class** — same drag, same close, same z-index, same backdrop. The distinction is only conceptual.

### App

The main float window opened from a card. One per llming. Triggered by clicking a widget. URL gets `?app=name`. Backdrop click / Escape / Back closes it.

```javascript
LlmingClient.openLlming('cameras')   // opens the cameras app
```

### Subapp

A secondary window opened from inside an app or card. Use cases:
- Click a single camera in the cameras app → fullscreen detail view
- Click a chart in a dashboard → expanded interactive view
- Click an email row → reply composer
- Settings dialog inside an app

Subapps **stack** on top of their parent app. Each gets a unique id (parent id + UUID), so multiple subapps from the same parent can coexist (cascade-positioned). Closing the parent does NOT close subapps automatically — subapps are independent windows.

```javascript
LlmingClient.openSubapp(parentId, componentName, props, opts)

// Example: open a single-camera detail subapp
LlmingClient.openSubapp('cameras', 'cameras-card', { camId: 'frontdoor', camName: 'Front' }, {
  title: 'Front Door',
  width_pct: 60,
  height_pct: 75,
  min_width: 480,
  min_height: 360,
})
```

Props are passed to the rendered Vue component. The same component can render differently based on props — e.g., the `cameras-card` component renders the multi-camera grid by default, but renders a single-camera detail view when `camId` is set.

### Unified Window Class

Both apps and subapps render through the same `floatWindows` reactive list and the same `<div class="hort-float-window">` template. They share:
- Drag handles, position, size, min-width/min-height
- Minimize / close buttons
- Backdrop dimming
- Escape / browser-back closes the topmost
- Resize handle at bottom-right

The only window-class difference: subapps have `isSubapp: true` and a `parentId` reference. The framework can use this for grouping (e.g., "close all subapps of cameras") but the rendering and lifecycle are identical.

## App Preferences (IndexedDB)

UI preferences that should persist across reloads (demo mode toggle, future settings) live in IndexedDB:

- **Database:** `hort-prefs`
- **Store:** `prefs`
- **Access:** `window.__hortPrefs.get(key)` / `window.__hortPrefs.set(key, value)`

### Demo Mode Persistence

Toggling demo mode (5x logo click, debug FAB switch, or `HortDemo.toggle()`) writes the new state to `prefs.demoMode`. On page reload, the boot sequence reads it and re-enables demo mode automatically — the user never has to re-toggle.

```javascript
// In page boot
window.__hortPrefs.get('demoMode').then(saved => {
  if (saved && !HortDemo.active) HortDemo.toggle();
});
```

This means a developer working on UI mockups can refresh the page freely without losing their demo session.

## Demo Data — Strict Separation

**Rule: Demo data NEVER comes from the UI.** All sample/mock data is provided exclusively by the llming backend (demo.js), never hardcoded in card.vue templates.

- Card.vue uses `vaultRef('name', 'key', EMPTY_DEFAULT)` — empty arrays, zeros, empty strings
- demo.js provides all sample data via its `vault:` section and `simulate()` function
- The card renders whatever the vault contains — it doesn't know or care if the data is real or demo
- When demo mode is off and no real llming is running, the card shows the empty default state

**This also applies to media.** Camera feeds, audio streams, or any binary content must come from the backend, not from hardcoded `<video src>` or `<img src>` in the template. The card template renders frames from a stream channel — same code path for real cameras and demo playback.

**One delivery path per pattern.** Demo and production share the same client-side delivery code:

- Vault: `vaultSet(owner, key, data)` → `LlmingClient._notifyVaultUpdate` (same notifier the WS dispatcher uses).
- Pulse: `ctx.emit(channel, payload)` → same handler dispatch as WS-delivered pulses.
- Stream: `ctx.stream(channel).emit(payload)` → `LlmingClient._handleStreamFrame` (same entrypoint as `stream.frame` over WS).

Demo MUST NOT push frames through the vault. Streams have their own dedicated channel — using the vault as a side-channel for binary data couples two unrelated patterns and creates two delivery paths the consumer has to handle. Keep them separate.

## Three Communication Patterns

OpenHORT has three distinct ways data flows from llming to UI. Each serves a different purpose. Don't mix them.

### 1. Vault — State Snapshots

**What:** Key-value state. Current value matters, history doesn't.

**Examples:** Room light on/off, CPU percentage, playlist metadata, email list, calendar events.

**Behavior:**
- Producer writes whenever state changes: `self.vault.set("state", data)`
- Consumer reads reactively: `vaultRef('system-monitor', 'state.cpu_percent', 0)`
- Multiple writes between client reads → only latest delivered (coalesced)
- No subscriber awareness needed. Producer writes regardless. Framework only sends over the wire if watchers exist.

**Not for:** High-frequency data, binary blobs, anything where individual updates matter.

### 2. Pulse — Events (Pub/Sub)

**What:** Fire-and-forget events. Every event matters, but the producer doesn't customize per subscriber.

**Examples:** "motion detected", "workflow failed", "new email arrived", "song changed", log lines, chat messages.

**Behavior:**
- Producer emits: `self.emit("motion_detected", { camera: "front" })`
- Consumer subscribes: `@pulse("motion_detected")` or `self.channels["motion_detected"].subscribe(handler)`
- Every subscriber gets every event, same data, no filtering
- Producer does NOT know who is listening or how many
- Producer does NOT produce custom data per listener
- If no subscribers, the event is simply not delivered over the wire (but still emitted internally for cross-llming use)

**Not for:** Continuous streams, binary data, anything requiring flow control or per-subscriber adaptation.

### 3. Streams — Continuous Binary/Frame Delivery

**What:** High-frequency, potentially large payloads where the producer is aware of its consumers and adapts.

**Two sub-types:**

#### 3a. Frame Streams (skippable)

**Examples:** Camera feeds, screen capture, video thumbnails, waveform visualization.

**Key property:** Individual frames can be skipped. Only the latest matters. The producer knows its subscribers and can optimize.

**Behavior:**
- Consumer subscribes with hints: `useStream('cameras:frontdoor', { displayWidth: 320 })`
- **Producer receives subscriber list** with parameters (display size, ACK speed)
- **Producer decides** capture rate and resolution. Zero subscribers → stop capturing entirely. One thumbnail subscriber → 2fps at 160px. Fullscreen viewer → 30fps at source resolution.
- **ACK-paced delivery**: client ACKs after rendering. Next frame only after ACK. Frames arriving while un-ACKed → single-slot buffer (latest wins, stale dropped).
- **Per-subscriber optimization**: screen capture can send different viewport crops to different viewers. Camera can encode at different resolutions.

**Client API:**
```javascript
const { frame, active } = useStream('cameras:frontdoor', {
  displayWidth: 320,
  displayHeight: 180,
})
// frame — reactive ref (blob URL), updates after each ACK cycle
// active — true when receiving
```

#### 3b. Continuous Streams (non-skippable)

**Examples:** Audio playback, voice chat, real-time sensor data logging.

**Key property:** Data must be delivered in order and continuously. Gaps are audible/visible. But when sync is lost (network hiccup, buffer overflow), it's better to **drop everything and restart cleanly** than to buffer and introduce latency.

**Behavior:**
- Continuous ordered delivery while connection is healthy
- If consumer falls behind (buffer exceeds threshold) → **hard reset**: drop all buffered data, signal producer to restart from current position
- Latency between creation and playback is minimized — never accumulates
- After reset, playback resumes from "now", not from where it left off

**Drop-and-restart** is fundamentally different from frame streams: frame streams silently skip stale frames one at a time. Continuous streams either flow perfectly or hard-reset to re-sync. There's no gradual degradation.

### Data Types

Frame streams and continuous streams are NOT limited to images and audio. Any data type works:

| Data | Pattern | Example payload |
|------|---------|----------------|
| Camera feed | Frame stream | WebP image blob |
| Screen capture | Frame stream | WebP image blob, per-subscriber viewport crop |
| Sensor readings | Frame stream | `{ temp: 22.3, humidity: 45, pressure: 1013 }` |
| Graph/chart data | Frame stream | `{ points: [...], timestamp: ... }` |
| Waveform visualization | Frame stream | `Float32Array` of amplitude samples |
| Audio playback | Continuous stream | Opus/PCM audio chunks |
| Voice chat | Continuous stream | Opus audio chunks |
| Live log tail | Continuous stream | Text lines (every line matters, reset on overflow) |
| Realtime sensor log | Continuous stream | Binary sensor packets |

The distinction is **skippable vs non-skippable**, not image vs audio vs data.

### Decorator API

#### Vault (existing)
```python
class SystemMonitor(Llming):
    def activate(self, config):
        self.vault.set("state", {"cpu": 0, "mem": 0})

    @pulse("tick:1hz")
    async def poll(self, data):
        self.vault.set("state", {"cpu": get_cpu(), "mem": get_mem()})
```

#### Pulse (existing)
```python
class Cameras(Llming):
    async def on_motion(self, camera_id):
        await self.emit("motion_detected", {"camera": camera_id})
```

#### Producer Side — Active push API

**Producers don't use decorators.** The `@stream` decorator is consumer-only (like `@pulse`). Producers actively manage their stream — they decide when to capture, what to send, and how to adapt to subscribers. The framework gives them subscriber awareness via `self.streams[name]`.

```python
from hort.llming import Llming

class Cameras(Llming):
    async def activate(self) -> None:
        # Declare the stream channel
        self.streams.declare("frame")
        # Watch for subscriber changes (framework calls when count or params change)
        self.streams["frame"].on_subscribers_changed(self._on_subs_changed)

    async def _on_subs_changed(self, subscribers: list[dict]) -> None:
        """Called by framework when subscribers join/leave/change params."""
        if not subscribers:
            self._stop_capture_loop()
            return
        max_w = max((s.get('width', 160) for s in subscribers), default=160)
        self._start_capture_loop(width=max_w)

    async def _capture_loop(self) -> None:
        while self._running:
            frame = await self.camera.capture()
            # Push to stream — framework handles per-subscriber ACK pacing
            await self.streams["frame"].emit(frame)
            # If no subscriber is ready, emit() returns immediately and the
            # frame is dropped (frame stream = latest wins). On a fast LAN
            # link, ACKs come back quickly and capture continues at full rate.
```

For **continuous streams** (audio, logs), the producer uses `emit_continuous()`:

```python
class AudioPlayer(Llming):
    async def activate(self) -> None:
        self.streams.declare("playback", continuous=True)
        self.streams["playback"].on_subscribers_changed(self._on_subs)

    async def _on_subs(self, subscribers: list[dict]) -> None:
        if subscribers and not self._playing:
            self._playing = True
            asyncio.create_task(self._play_loop())
        elif not subscribers:
            self._playing = False

    async def _play_loop(self) -> None:
        decoder = self.open_audio()
        while self._playing:
            chunk = await decoder.read(1024)
            try:
                # blocks on backpressure; raises StreamReset on consumer desync
                await self.streams["playback"].emit_continuous(chunk)
            except StreamReset:
                # Consumer fell behind — skip ahead to current time, restart cleanly
                decoder.seek_to_now()
```

Subscriber params are **generic dicts** — the producer defines what it accepts (width, region, sample_rate, etc.). Framework passes them through unchanged.

#### Consumer Side — `@stream` decorator

Llmings consume streams from other llmings via the `@stream` decorator. Receiver-only. The callback receives a single data dict (or auto-parsed Pydantic model).

```python
class SecurityDashboard(Llming):
    @stream("cameras:frame")
    async def on_camera_frame(self, data: dict) -> None:
        await self.analyze_motion(data["frame"])

    @stream("sensors:readings")
    async def on_sensor_data(self, data: dict) -> None:
        if data.get('temp', 0) > 40:
            await self.emit("temp_alert", data)
```

For **cards** (client-side), `useStream()` is the consumer API:

```javascript
// Frame stream — generic params, producer decides what to do with them
const cam = useStream('cameras:frame', { width: 320, height: 180 })
const sensor = useStream('sensors:readings', { sample_rate: 10 })
const screen = useStream('screen:viewport', { region: 'top-left', width: 640 })

// Continuous stream
const audio = useStream('player:playback', { continuous: true })
const logs = useStream('claude:output', { continuous: true })
```

The params object is **freeform** — the card sends whatever the producer expects. No framework-imposed schema.

### Callback Convention (all patterns)

All llming callbacks — powers, pulses, streams — follow the same rule: **`self` + one data parameter**. Never positional args. Always type-annotated.

**Transport is always JSON/dict.** On the wire, between processes, across IPC — data is always a plain dict. Packages are decoupled (hort framework, llmings, llming-com don't import each other), so no shared types cross boundaries.

**Automatic Pydantic conversion.** The framework inspects the callback's type annotation. If the parameter type is a Pydantic model, the framework parses the incoming dict into it before calling. If the return type is a Pydantic model, the framework calls `.model_dump()` on the result before sending. The developer just writes typed code — the framework handles serialization.

```python
# Simple — dict in, dict out (no conversion)
@power("get_status")
async def get_status(self, data: dict) -> dict:
    return {"cpu": get_cpu()}

# Typed — framework auto-parses dict → Model, auto-dumps Model → dict
from pydantic import BaseModel

class StatusRequest(BaseModel):
    include_disks: bool = False

class StatusResponse(BaseModel):
    cpu: float
    mem: float
    disks: list[dict] = []

@power("get_status")
async def get_status(self, data: StatusRequest) -> StatusResponse:
    return StatusResponse(
        cpu=get_cpu(),
        mem=get_mem(),
        disks=get_disks() if data.include_disks else [],
    )
```

Both styles work. The transport is identical — JSON dict on the wire either way. The framework checks `if annotation is not dict and issubclass(annotation, BaseModel)` and converts automatically.

**Same for all patterns:**

```python
# Pulse — dict (simple)
@pulse("motion_detected")
async def on_motion(self, data: dict) -> None:
    camera_id = data.get("camera", "")
    await self.alert(camera_id)

# Pulse — Pydantic (framework parses automatically)
class MotionEvent(BaseModel):
    camera: str
    confidence: float = 0.0

@pulse("motion_detected")
async def on_motion(self, data: MotionEvent) -> None:
    if data.confidence > 0.8:
        await self.alert(data.camera)

# Stream consumer — dict (decorators are receiver-only)
@stream("cameras:frame")
async def on_frame(self, data: dict) -> None:
    await self.analyze(data["frame"])

# Stream consumer — Pydantic (framework auto-parses)
class FrameEvent(BaseModel):
    frame: bytes
    timestamp: float = 0.0
    format: str = "webp"

@stream("cameras:frame")
async def on_frame(self, data: FrameEvent) -> None:
    await self.analyze(data.frame)
```

(Stream producers don't use decorators — they push via `self.streams[name].emit()`.)

**Rules:**
- Parameter annotation is `dict` → passed as-is
- Parameter annotation is a `BaseModel` subclass → framework calls `Model(**incoming_dict)`
- Return annotation is `dict` → sent as-is
- Return annotation is a `BaseModel` subclass → framework calls `result.model_dump()`
- No annotation → treated as `dict` (but violates the type annotation rule — always annotate)

### Summary

| | Vault | Pulse | Frame Stream | Continuous Stream |
|-|-------|-------|-------------|--------------------|
| Producer API | `self.vault.set(key, data)` | `self.emit(channel, data)` | `self.streams[name].emit(data)` | `self.streams[name].emit_continuous(chunk)` |
| Producer declares | `vault` is implicit | implicit on first emit | `self.streams.declare("name")` | `self.streams.declare("name", continuous=True)` |
| Producer sees subscribers | No | No | **Yes** — `on_subscribers_changed()` | **Yes** — `on_subscribers_changed()` |
| Consumer (Llming) | `vault_ref()` descriptor | `@pulse("channel")` | `@stream("owner:name")` | `@stream("owner:name")` |
| Consumer (Card) | `vaultRef('owner', 'key')` | `@pulse` handler in card | `useStream('owner:name')` | `useStream('owner:name')` |
| Data type | JSON | JSON | Any (binary, JSON, text) | Any (binary, JSON, text) |
| Skippable | Latest wins | No | Yes (latest wins) | No (reset on overflow) |
| Latency model | Eventual | Best-effort | ACK-paced + pre-buffer | Zero-accumulation, drop+restart |

### Demo Mode

All four patterns work identically in demo mode — and crucially, each pattern has **one** delivery path on the client. Demo writes through the same notifier/dispatcher the WS handler uses; it does not piggyback on a different pattern.

| Pattern | Demo producer | Client entrypoint (shared with WS) |
|---|---|---|
| Vault | `ctx.vault.set(key, data)` | `LlmingClient._notifyVaultUpdate(owner, key, data)` |
| Pulse | `ctx.emit(channel, payload)` | per-channel handler dispatch |
| Frame stream | `ctx.stream(channel).emit(blobUrl)` | `LlmingClient._handleStreamFrame(channel, payload)` (ACK gate runs here) |
| Continuous stream | `ctx.stream(channel).emit(chunk)` | `LlmingClient._handleStreamFrame(channel, payload)` |

```js
// cameras/demo.js — pushing frames through the stream API, not the vault
const stream = ctx.stream('cameras:frontdoor');
canvas.toBlob(blob => {
  stream.emit(URL.createObjectURL(blob));
}, 'image/webp', 0.7);
```

The card uses the same `useStream`/`vaultRef`/`@pulse` API regardless of whether data comes from a real llming or a demo simulation. Do not write frames into the vault as a workaround — the consumer has exactly one code path per pattern, and that path is the production path.
