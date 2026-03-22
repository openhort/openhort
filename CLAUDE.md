# openhort

Remote window viewer — watch and control your machine from your phone/tablet.

## Architecture

- **Server:** FastAPI (Python 3.12+), HTTP on 8940, HTTPS on 8950 (self-signed cert)
- **UI:** Quasar/Vue 3 SPA in `hort/static/index.html` (UMD, no build step)
- **Communication:** llming-com session-based WebSocket (control WS for JSON, stream WS for binary)
- **Capture:** macOS Quartz API via pyobjc (`CGWindowListCreateImage`) — replaceable via extension system
- **Streaming:** Dedicated binary WebSocket per window, JPEG frames
- **State:** Client-side state in localStorage (groups, per-window zoom, settings)

## Key Files

- `hort/app.py` — FastAPI routes, session creation, WebSocket endpoints, server startup
- `hort/session.py` — Session entry and registry (built on llming-com)
- `hort/controller.py` — Control WebSocket message handler (HortController)
- `hort/stream.py` — Binary WebSocket stream transport (JPEG frames)
- `hort/models.py` — Pydantic models (strict types, frozen where appropriate)
- `hort/screen.py` — Window screenshot capture (Quartz → PIL → JPEG)
- `hort/windows.py` — Window listing/filtering (Quartz + SkyLight)
- `hort/input.py` — Input simulation (mouse/keyboard via Quartz CGEvent + AX API)
- `hort/spaces.py` — macOS Spaces detection and switching (SkyLight)
- `hort/network.py` — LAN IP detection, QR code generation
- `hort/cert.py` — Self-signed TLS certificate generation
- `hort/ext/` — Extension system (types, manifest, registry)
- `hort/containers/` — Container management (base ABC, Docker provider, registry)
- `hort/static/index.html` — Quasar/Vue 3 mobile-first UI
- `hort/static/vendor/` — Pre-compiled Vue 3, Quasar, Plotly.js, Material Icons, hort-ext.js
- `extensions/core/macos_windows/` — macOS platform extension (reference implementation)

## Communication Protocol

All control communication flows through a single JSON WebSocket per session:

1. `POST /api/session` → `{session_id}`
2. `WebSocket /ws/control/{session_id}` — JSON messages (list_windows, get_thumbnail, get_status, get_spaces, switch_space, stream_config, input, heartbeat)
3. `WebSocket /ws/stream/{session_id}` — binary JPEG frames (separate from control)

## Guidelines

- [UX Guidelines](docs/ux-guidelines.md) — interaction model, fit modes, panning rules, resolution strategy
- [Extension System](docs/extensions.md) — plugin architecture, provider interfaces, creating extensions
- [Container Environments](docs/containers.md) — Docker/Azure container management, preview panel

## Quality Standards

- 100% test coverage (`pytest --cov=hort`)
- mypy strict on `hort/` (tests and extensions excluded)
- Pydantic v2 for all data models
- OS-level Quartz wrappers isolated behind `_raw_*` functions for testability

## Running

```bash
poetry run python run.py
```

Requires Screen Recording permission for the terminal app in System Settings (macOS).

Dev mode (`--dev` or `LLMING_DEV=1`) enables:
- `uvicorn --reload` — auto-restarts on Python changes in `hort/`
- Client-side hot-reload — browser refreshes on `index.html` changes

Note: dev mode runs a single uvicorn process (HTTPS only on the main port) instead of the dual HTTP+HTTPS production setup.
