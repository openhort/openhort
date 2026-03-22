# UX Guidelines — openhort

## Target Devices

**Primary:** Tablets (iPad, Android tablets) — the sweet spot for remote monitoring.
**Secondary:** Smartphones (iPhone, Android phones) and desktop PCs.

All interactions must work well across all three. When trade-offs are necessary, optimize for tablet ergonomics first.

## Design Principles

### 1. Glanceable from a Distance

The user is often on a treadmill or across the room. Text must be large enough to read at arm's length on a tablet. High-contrast dark theme. No small, fiddly controls in the main workflow.

### 2. Thumb-Friendly

- Tap targets: minimum 44x44px (Apple HIG).
- Primary actions (switch window, go back) reachable with thumbs in landscape.
- No hover-only interactions — everything must work with touch.
- Swipe gestures for the most common action (switching windows).

### 3. Minimal Chrome, Maximum Content

- The stream image dominates the viewport.
- Header and controls auto-hide or stay minimal.
- Settings and secondary controls live behind a gear icon, not on-screen.
- Thumbnail strip at the bottom is compact — enough to tap, not enough to occlude.

### 4. Instant Feedback

- Window switching has a visible transition (fade) so the user knows something happened.
- FPS counter confirms the stream is live.
- Observer count confirms the connection is active.

## Interaction Model

### Fit Modes

| Mode | Behavior | Panning | When |
|---|---|---|---|
| **Auto-fit** | Image fits entirely in viewport (both dimensions) | No panning. Swipe left/right switches windows. | Default on every window switch. |
| **Fit vertical** | Image fills viewport height; may overflow horizontally | Vertical panning only (iPhone-style scroll). Horizontal locked. | User activates via button or `V` key. Useful for ultrawide monitors (5140x1440). |
| **Custom zoom** | User has pinched/scrolled to zoom | Full 2D panning. | Enters automatically on any zoom gesture. |

### Panning Rules

- **No panning in auto-fit.** The image is fully visible. Swipe gestures are reserved for window navigation.
- **Vertical-only in fit-vertical.** Like scrolling a tall webpage on a phone. Prevents accidental horizontal drift.
- **Full pan in custom zoom.** The user explicitly zoomed in and needs to explore.

### Navigation

- **Swipe left/right** (auto-fit only): switch windows.
- **Side arrows**: always visible, switch windows.
- **Bottom thumbnail strip**: tap to jump.
- **Keyboard** (PC): arrow keys, A/D, F/V/G/1/2/3.
- **Overview grid** (G or grid icon): see all windows at once, tap to switch.

## Resolution Strategy

The client must request images at a resolution that matches its actual display:

```
max_width = min(screen_width * devicePixelRatio, user_setting)
```

- A phone (390px, 3x DPR) requests 1170px — sharp but not wasteful.
- A tablet (1024px, 2x DPR) requests 2048px.
- A PC (1920px, 1x DPR) requests 1920px.
- The settings panel allows override for bandwidth-constrained scenarios.

The server sends exactly what the client requests. No over-delivery.

## Session Management

- Each viewer client creates a session via `POST /api/session`.
- A control WebSocket (`/ws/control/{session_id}`) carries all JSON commands.
- A separate binary WebSocket (`/ws/stream/{session_id}`) carries JPEG frames.
- The server tracks live observer count (sessions with active stream).
- Observer count is available via `{type: "get_status"}` on the control WS.
- Disconnections are detected immediately (WebSocket close) and cleaned up.
- Sessions with no active WebSocket expire after 5 minutes (llming-com TTL).

## Accessibility

- All interactive elements have visible focus indicators.
- Icon buttons have `title` attributes for tooltips.
- Color is never the only indicator of state (icons + color).
- Touch targets meet minimum size requirements on all device classes.
