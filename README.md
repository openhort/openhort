# openhort

Remote window viewer and controller — watch and interact with your Mac from your phone, tablet, or another computer over your local network.

## Quick Start

```bash
git clone <repo-url> openhort
cd openhort
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
| 8940 | HTTP | Landing page, QR code |
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

In dev mode:
- **Python changes** — uvicorn runs with `--reload` on HTTP port 8940, auto-restarts on any `.py` change in `hort/`.
- **HTML/CSS/JS changes** — the client-side hot-reload WebSocket (`/ws/devreload`) detects changes to `index.html` and refreshes the browser automatically.
- **HTTPS proxy** — an nginx container in `tools/local-https/` terminates TLS on port 8950 and proxies to the app. During uvicorn restarts it shows a "Server restarting..." page instead of a connection error.

```bash
# One-time setup for HTTPS proxy:
cd tools/local-https && docker compose up -d
```

Zero overhead in production (no reload watcher, no dev script injected, dual HTTP+HTTPS served directly).

## Communication Protocol

All control communication uses a session-based JSON WebSocket (via [llming-com](https://github.com/Alyxion/llming-com)). Image streams use a separate binary WebSocket.

### Session Lifecycle

1. Client sends `POST /api/session` → receives `{session_id}`
2. Client connects control WS to `/ws/control/{session_id}`
3. Client connects stream WS to `/ws/stream/{session_id}` when viewing a window

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Landing page with QR code |
| `/viewer` | GET | Main viewer app (Quasar/Vue 3) |
| `/api/session` | POST | Create a new viewer session |
| `/api/hash` | GET | Static file content hash, dev mode flag |
| `/api/icon/{size}` | GET | Generated PNG app icon |
| `/manifest.json` | GET | PWA manifest |
| `/sw.js` | GET | Service worker |
| `/ws/control/{session_id}` | WebSocket | JSON control channel (all commands) |
| `/ws/stream/{session_id}` | WebSocket | Binary JPEG frame stream |
| `/ws/devreload` | WebSocket | Dev mode file-change notifications |

### Control WebSocket Messages

| Client sends | Server responds |
|---|---|
| `{type: "list_windows"}` | `{type: "windows_list", windows: [...], app_names: [...]}` |
| `{type: "get_thumbnail", window_id: N}` | `{type: "thumbnail", window_id: N, data: "<base64>"}` |
| `{type: "get_status"}` | `{type: "status", observers: N, version: "..."}` |
| `{type: "get_spaces"}` | `{type: "spaces", spaces: [...], current: N, count: N}` |
| `{type: "switch_space", index: N}` | `{type: "space_switched", ok: bool}` |
| `{type: "stream_config", window_id: N, ...}` | `{type: "stream_config_ack", window_id: N}` |
| `{type: "input", event_type: "click", ...}` | *(no response)* |
| `{type: "heartbeat"}` | `{type: "heartbeat_ack"}` |

## Architecture

```
hort/
├── app.py          FastAPI routes, session creation, WS endpoints
├── session.py      Session entry and registry (llming-com)
├── controller.py   Control WS message handler (HortController)
├── stream.py       Binary stream transport (JPEG frames)
├── models.py       Pydantic models (WindowInfo, StreamConfig, InputEvent, etc.)
├── screen.py       Window capture (Quartz CGWindowListCreateImage → PIL → JPEG)
├── windows.py      Window listing/filtering (Quartz + SkyLight)
├── input.py        Input simulation (mouse/keyboard via Quartz CGEvent)
├── spaces.py       macOS Spaces detection and switching (SkyLight)
├── network.py      LAN IP detection, QR code generation
├── cert.py         Self-signed TLS certificate generation
├── ext/            Extension system (types, manifest, registry)
├── extensions/     Built-in platform extensions
│   └── core/
│       ├── macos_windows/   macOS (Quartz + SkyLight)
│       └── linux_windows/   Linux via Docker (Xvfb + xdotool)
└── static/
    ├── index.html  Quasar/Vue 3 mobile-first UI
    └── vendor/     Pre-compiled Vue, Quasar, Plotly.js, Material Icons
```

All client state (groups, per-window zoom, settings) is stored in the browser's localStorage. Multiple clients can connect independently with their own state.

## Extension System

The extension system makes platform capabilities replaceable and composable. See [docs/extensions.md](docs/extensions.md) for the full specification.

Key concepts:
- **`PlatformProvider`** — unified ABC for window listing, capture, input, workspaces
- **`ExtensionBase`** — lifecycle hooks (`activate`/`deactivate`) for all extensions
- **`HortExtension`** (JS) — client-side extension base for Quasar UI panels
- Built-in extensions live in `hort/extensions/core/`

## Quality

```bash
poetry run pytest tests/ --cov=hort    # 227 tests, 100% coverage
poetry run mypy hort/                   # strict mode, 0 errors
```

### Playwright UI Tests

End-to-end tests that render the UI in headless Chromium and take screenshots:

```bash
# One-time setup
poetry add --group dev playwright pytest-playwright
poetry run playwright install chromium

# Run UI tests (marked as integration, skipped by default)
poetry run pytest tests/test_ui_playwright.py -v -m integration
```

Tests verify: landing page renders, Quasar/Vue mount without errors, picker shows windows, viewer streams frames, no broken images, mobile and tablet viewports. Screenshots saved to `screenshots/`.
