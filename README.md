# llming-control

Remote macOS window viewer and controller — watch and interact with your Mac from your phone, tablet, or another computer over your local network.

## Quick Start

```bash
cd /Users/michael/projects/llming-control
poetry install
poetry run python run.py
```

Open `http://<your-LAN-IP>:8940` in a browser, or scan the QR code from your phone.

## macOS Permissions

The app needs two permissions granted to your **terminal application** (iTerm2, Terminal.app, etc.):

### Screen Recording (required)

Allows capturing window contents.

**System Settings → Privacy & Security → Screen & System Audio Recording**

1. Open **System Settings** (Apple menu → System Settings)
2. Navigate to **Privacy & Security** in the left sidebar
3. Scroll down and click **Screen & System Audio Recording**
4. Click the **+** button, find and add your terminal app (e.g. iTerm2)
5. Restart your terminal after granting

Without this permission, window captures will be blank/transparent.

### Accessibility (required for active mode)

Allows simulating mouse clicks, keyboard input, and scroll events on the remote Mac.

**System Settings → Privacy & Security → Accessibility**

1. Open **System Settings** (Apple menu → System Settings)
2. Navigate to **Privacy & Security** in the left sidebar
3. Click **Accessibility**
4. Click the **+** button, find and add your terminal app (e.g. iTerm2)
5. Restart your terminal after granting

Without this permission, active mode clicks and keyboard input will silently fail.

## Features

### Viewer Mode (default)

Watch your Mac windows remotely. Optimized for monitoring from a treadmill, couch, or across the room.

- **Window picker** — browse all open windows, filter by app
- **Live stream** — JPEG frames over WebSocket, configurable FPS/quality
- **Auto-fit** — image fits the viewport by default
- **Fit vertical** — fills height for ultrawide monitors (5140x1440), vertical-only panning
- **Zoom** — scroll wheel or pinch to zoom, click-drag or touch to pan
- **Minimap** — appears when zoomed in, shows viewport position, click to navigate
- **L/M/R jump** — quick buttons to jump to left/center/right of ultrawide windows

### Active Mode

Interact with your Mac remotely — click, type, scroll.

- **Left click** — tap/click on the stream
- **Double-click** — double-tap/double-click
- **Right-click** — right-click or long press
- **Scroll** — scroll wheel (mouse) or two-finger scroll (trackpad)
- **Keyboard** — all keys forwarded with modifiers (Shift, Ctrl, Alt, Cmd)

### Window Navigation

- **Arrow keys / A,D** — previous/next window
- **Swipe left/right** — switch windows (phone/tablet, auto-fit mode only)
- **Bottom thumbnail strip** — tap to jump to any window
- **Overview grid** — see all windows at once (G key or grid icon)

### Groups

Create named groups of windows (e.g. "Debug Pair" with Windsurf + Chrome) and cycle through just those.

- Groups persist in browser localStorage
- Each client has independent groups
- Double-click or right-click a group chip to rename/delete

### Smart Resolution

The client reports its screen size and pixel density. The server never sends more pixels than the client can display:

- Phone (390px, 3x DPR) → max 1170px
- Tablet (1024px, 2x DPR) → max 2048px
- Desktop (1920px, 1x DPR) → max 1920px

Override in the gear menu if needed.

## Keyboard Shortcuts (Viewer)

| Key | Action |
|-----|--------|
| `I` | Toggle active mode |
| `F` | Auto-fit |
| `V` | Fit vertical |
| `G` | Overview grid |
| `1` / `2` / `3` | Jump left / center / right |
| `←` / `A` | Previous window |
| `→` / `D` | Next window |
| `Esc` | Back to picker (or exit active mode) |

## Network Setup

| Port | Protocol | Purpose |
|------|----------|---------|
| 8940 | HTTP | Landing page, QR code, API |
| 8950 | HTTPS | Secure streaming (self-signed cert) |

Both ports serve the same app. HTTPS is needed for `wss://` WebSocket on mobile browsers. On first connect over HTTPS, accept the self-signed certificate warning (Advanced → Proceed).

The QR code on the landing page points to the HTTPS URL for easy phone setup.

## Developer Mode

Enables hot-reload — the browser automatically refreshes when you edit `index.html`.

Activate via `.env` file (already present in the repo):

```
LLMING_DEV=1
```

Or via CLI flag:

```bash
poetry run python run.py --dev
```

The server watches static files every 500ms and pushes reload notifications over a dedicated WebSocket (`/ws/devreload`). Zero overhead in production (script not injected when dev mode is off).

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Landing page with QR code |
| `/viewer` | GET | Main viewer app (cache-busted) |
| `/api/windows` | GET | List windows (optional `?app_filter=Chrome`) |
| `/api/windows/{id}/thumbnail` | GET | Single window screenshot (JPEG) |
| `/api/status` | GET | Observer count, version |
| `/api/hash` | GET | Static file content hash, dev mode flag |
| `/ws/stream` | WebSocket | Live window stream + input events |
| `/ws/devreload` | WebSocket | Dev mode file-change notifications |

## Architecture

```
control/
├── app.py          FastAPI routes, WebSocket streaming, observer tracking
├── models.py       Pydantic models (WindowInfo, StreamConfig, InputEvent, etc.)
├── screen.py       Window capture (Quartz CGWindowListCreateImage → PIL → JPEG)
├── windows.py      Window listing/filtering (Quartz CGWindowListCopyWindowInfo)
├── input.py        Input simulation (mouse/keyboard via Quartz CGEvent)
├── network.py      LAN IP detection, QR code generation
├── cert.py         Self-signed TLS certificate generation
└── static/
    └── index.html  Complete mobile-first UI (vanilla JS)
```

All client state (groups, per-window zoom, settings) is stored in the browser's localStorage. Multiple clients can connect independently with their own state.

## Quality

```bash
poetry run pytest tests/ --cov=control    # 127 tests, 100% coverage
poetry run mypy control/                   # strict mode, 0 errors
```
