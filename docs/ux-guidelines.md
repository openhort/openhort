# UX Guidelines — openhort

## Target Devices

**Primary:** Tablets (iPad, Android tablets) — the sweet spot for remote monitoring.
**Secondary:** Smartphones (iPhone, Android phones) and desktop PCs.

All interactions must work well across all three. When trade-offs are necessary, optimize for tablet ergonomics first.

## Electric Color Palette

All colors use CSS custom properties defined in `:root`. The palette is called **Electric** — a dark blue background with bright blue accents and high-contrast white-blue text.

| Variable | Hex | Usage |
|---|---|---|
| `--el-bg` | `#0a0e1a` | Page background |
| `--el-surface` | `#111827` | Cards, panels, headers |
| `--el-border` | `#1e3a5f` | Borders, dividers, placeholder backgrounds |
| `--el-primary` | `#3b82f6` | Primary actions, active states, links |
| `--el-accent` | `#60a5fa` | Hover states, secondary highlights |
| `--el-text` | `#f0f4ff` | Primary text (white-blue) |
| `--el-text-dim` | `#94a3b8` | Secondary text, labels, timestamps |
| `--el-danger` | `#ef4444` | Destructive actions (close, delete) |
| `--el-success` | `#22c55e` | Positive actions (accept, confirm) |

**Rules:**
- Never use hardcoded hex colors in CSS — always reference the variable.
- Server-side colors (landing page, manifest, icon generator) use the raw hex values from this palette.
- The Quasar `brand` config matches: `primary: '#3b82f6'`, `secondary: '#1e3a5f'`, `accent: '#60a5fa'`.

## Design Principles

### 1. Glanceable from a Distance

The user is often on a treadmill or across the room. Text must be large enough to read at arm's length on a tablet. High-contrast dark theme (Electric palette). No small, fiddly controls in the main workflow.

### 2. Thumb-Friendly

- Tap targets: minimum 44x44px (Apple HIG).
- Primary actions (switch panel, go back) reachable with thumbs in landscape.
- No hover-only interactions — everything must work with touch.
- Swipe gestures for the most common action (switching windows).

### 3. Minimal Chrome, Maximum Content

- The stream/terminal dominates the viewport.
- Header and controls auto-hide or stay minimal.
- Settings and secondary controls live behind a gear icon, not on-screen.

### 4. Instant Feedback

- Panel switching has a visible transition.
- FPS counter confirms the stream is live.
- Observer count confirms the connection is active.

## Unified Grid (Landing Page)

The landing page is a responsive grid of **panel cards**. Every active panel — window stream, terminal, or plugin — appears as a card with a large 16:10 thumbnail preview.

### Grid Layout

```css
grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
```

| Device | Card min width | Typical columns |
|---|---|---|
| Phone (360px) | 150px | 2 |
| Tablet (768px) | 200px | 3–4 |
| PC (1440px) | 200px | 5–7 |

### Card Types

| Card | Thumbnail | Subtitle |
|---|---|---|
| **Window** | Live JPEG screenshot | App name + window title |
| **Terminal** | Terminal icon (Phosphor `ph-terminal-window`) | Shell + target |
| **Plugin** | Plugin-defined icon | Plugin title |
| **"+ New Panel"** | Large plus icon | "New Panel" (always first in grid) |

### Navigation

- Tap a card → opens the panel full-screen (viewer for windows, terminal for terminals, plugin view for plugins).
- Back button → returns to the grid.
- Groups bar filters which windows appear.
- Target bar filters by machine (All / This Mac / Linux containers).
- Keyboard: arrow keys/A/D for prev/next window in viewer, Escape to return to grid.

## Panel Plugin Concept

Every panel in openhort follows the same lifecycle:

```
Grid Card → Full-Screen View → Close (back to grid)
```

### Built-in Panel Types

- **Window Stream** — live JPEG streaming with zoom/pan/fit and active mode (remote input).
- **Terminal** — PTY-backed terminal via xterm.js with mobile toolbar and auto-detected action buttons.

### Per-Target Panel Providers

Each target (machine) provides its own list of available panel types. The "New Panel" (`+`) card is scoped to its target group — clicking it on "This Mac" offers macOS panels, clicking it on a Linux container offers Linux panels.

Built-in panel types are available on all targets:
- **Terminal** — always available (spawns a shell on that target)

Extension panels register via `HortExtension` and declare which targets they support. For example, a "Chrome DevTools" panel might only be available on targets that have Chrome running.

The `+` card sits to the left of the windows in each target group, followed by any active terminals for that target, then the window thumbnails.

### Extension Panels

Third-party panels extend `HortExtension` with panel metadata:

```javascript
class MyPanel extends HortExtension {
    static id = 'my-panel';
    static name = 'My Panel';
    static panelTitle = 'My Custom Panel';    // shown in "New Panel" dialog
    static panelIcon = 'ph ph-chart-bar';     // grid card icon

    setup(app, Quasar) {
        // Register Vue component for the full-screen view
        app.component('my-panel-view', { ... });
    }
}
HortExtension.register(MyPanel);
```

The "New Panel" (`+`) card in the grid opens a Quasar dialog listing all available panel types — built-in terminals plus any registered extension panels.

### Panel Lifecycle

1. **Spawn**: user taps "+" → selects panel type → server creates the session
2. **Grid card**: panel appears in the grid with its icon/thumbnail and title
3. **Open**: user taps the card → full-screen view
4. **Close**: user taps "Close" → Quasar confirmation dialog → session destroyed → card removed

## Style Rules

### No JavaScript Dialogs

**NEVER** use `alert()`, `confirm()`, or `prompt()`. Always use Quasar dialogs:

```javascript
// ❌ WRONG
if (confirm('Delete this?')) { ... }

// ✅ CORRECT
Quasar.Dialog.create({
    title: 'Delete',
    message: 'Delete this item?',
    dark: true,
    ok: { label: 'Delete', color: 'negative' },
    cancel: { label: 'Cancel', flat: true },
}).onOk(() => { ... });
```

Quasar dialogs respect the dark theme, are mobile-friendly, and don't block the browser's event loop.

### Component Style

- All UI components use Quasar elements where available (`q-btn`, `q-dialog`, `q-select`, etc.).
- Custom CSS uses the Electric palette variables — no hardcoded colors.
- Icons use Phosphor Icons (regular/bold/fill) — already loaded via CDN.
- Material Icons are available via Quasar for Quasar components.

## Interaction Model

### Fit Modes (Window Viewer)

| Mode | Behavior | Panning | When |
|---|---|---|---|
| **Auto-fit** | Image fits entirely in viewport (both dimensions) | No panning. Swipe left/right switches windows. | Default on every window switch. |
| **Fit vertical** | Image fills viewport height; may overflow horizontally | Vertical panning only. Horizontal locked. | User activates via button or `V` key. |
| **Custom zoom** | User has pinched/scrolled to zoom | Full 2D panning. | Enters automatically on any zoom gesture. |

### Panning Rules

- **No panning in auto-fit.** The image is fully visible. Swipe gestures are reserved for window navigation.
- **Vertical-only in fit-vertical.** Like scrolling a tall webpage on a phone.
- **Full pan in custom zoom.** The user explicitly zoomed in and needs to explore.

## Resolution Strategy

The client reports its screen size and pixel density. The server captures at the requested resolution:

```
max_width = min(screen_width * devicePixelRatio, user_setting)
```

- Phone (390px, 3x DPR) → max 1170px
- Tablet (1024px, 2x DPR) → max 2048px
- PC (1920px, 1x DPR) → max 1920px

Grid thumbnails are captured at 600px width for sharp display in the card grid.

## Session Management

- Each viewer client creates a session via `POST /api/session`.
- Control WebSocket (`/ws/control/{session_id}`) carries all JSON commands.
- Binary WebSocket (`/ws/stream/{session_id}`) carries JPEG frames.
- Terminal WebSocket (`/ws/terminal/{terminal_id}`) carries PTY I/O.
- Terminal sessions persist across server restarts via the `hort-termd` daemon.
- Docker containers are auto-discovered every 10 seconds.

## Accessibility

- All interactive elements have visible focus indicators.
- Icon buttons have `title` attributes for tooltips.
- Color is never the only indicator of state (icons + color).
- Touch targets meet minimum size requirements on all device classes.

## Essential Libraries

**Plotly.js** is the standard charting library. All plugins that display charts, graphs, gauges, or data visualizations MUST use Plotly.js (pre-compiled at `static/vendor/plotly.min.js`). Do not introduce alternative chart libraries.

Plotly provides: line/bar/pie charts, gauges, heatmaps, 3D plots, and responsive layouts out of the box. Use `paper_bgcolor: 'transparent'` and `plot_bgcolor: 'transparent'` with `font.color: 'var(--el-text-dim)'` to match the Electric palette.

## Navigation Model — Shorts-Style Zapping

The navigation is inspired by **YouTube Shorts**: users should be able to efficiently zap through their llmings (windows, terminals, plugin panels) with minimal friction, having all information at their fingertips.

**Key principles:**

1. **Single-swipe navigation** — On mobile, swipe left/right or tap card edges to cycle through llmings. Each llming fills the viewport like a "short".
2. **Cards as entry points** — Every llming, spirit, and system appears as a unified card in the grid. Tap once to peek (preview), tap again to enter full screen.
3. **Consistent card layout** — Whether it's a window screenshot, terminal, plugin dashboard, or system status — all use the same `.grid-card` with `.card-thumb-icon` or `.grid-card-thumb` + `.grid-card-info`.
4. **Glanceable thumbnails** — Spirits render live thumbnails via `renderThumbnail(ctx, 320, 200)`. The grid is a dashboard — you should be able to see the state of your entire system at a glance without opening anything.
5. **Constrained detail panels** — Config and spirit detail panels never span full width. Max-width 420px (smartphone-proportioned). This works on both landscape tablet and portrait phone.

**Three views, same feel:**

| View | Content | Card behavior |
|---|---|---|
| **Llmings** | Windows + terminals + plugin UIs | Tap → full viewer, swipe to cycle |
| **Spirits** | Background plugins with live stats | Tap → config panel with toggles |
| **Config** | All plugins with feature management | Tap → detail with capabilities |

**Responsive breakpoints:**

| Device | Grid columns | Card min-width | Detail panel |
|---|---|---|---|
| Phone portrait | 2 | 150px | Full width, max 420px |
| Phone landscape | 3-4 | 150px | Centered, max 420px |
| Tablet | 4-5 | 200px | Centered, max 420px |
| Desktop | 6-8 | 200px | Centered, max 420px |

## File Size Constraints

**Enforce: no single file should exceed ~1000 lines.**

The main exception is `index.html` — a single-file Quasar UMD SPA with no build step. CSS is extracted to `hort.css`. Component extraction is limited by Vue UMD's closure-based scope (components share state with the main IIFE).

| File | Purpose | Target |
|---|---|---|
| `hort.css` | All styles | < 500 lines |
| `hort-ext.js` | Extension base class | < 300 lines |
| `hort-widgets.js` | Shared widget components | < 400 lines |
| `hort-plugins-ui.js` | Plugin manager + loader | < 250 lines |
| `index.html` | Core logic + templates | ~2500 lines (UMD constraint) |
| Plugin `panel.js` | Per-plugin UI | < 200 lines each |

To keep `index.html` manageable:
- CSS is in `hort.css` (never inline)
- Shared components are in vendor JS files
- Plugin UIs are in extension directories
- Only core app logic and template structure stay in index.html
