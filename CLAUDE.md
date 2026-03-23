# openhort

Remote window viewer — watch and control your machine from your phone/tablet.

## Architecture

- **Server:** FastAPI (Python 3.12+), HTTP on 8940, HTTPS on 8950 (nginx proxy)
- **UI:** Quasar/Vue 3 SPA in `hort/static/index.html` (UMD, no build step)
- **Communication:** llming-com session-based WebSocket (control WS for JSON, stream WS for binary)
- **Capture:** macOS Quartz API via pyobjc — replaceable via extension system
- **Streaming:** Dedicated binary WebSocket per window, JPEG frames
- **Terminal:** PTY-backed terminals via xterm.js, supports local and Docker targets
- **State:** Client-side state in localStorage (groups, per-window zoom, settings)

## Key Files

- `hort/app.py` — FastAPI routes, session creation, WebSocket endpoints, server startup
- `hort/session.py` — Session entry and registry (built on llming-com)
- `hort/controller.py` — Control WebSocket message handler (HortController)
- `hort/stream.py` — Binary WebSocket stream transport (JPEG frames)
- `hort/terminal.py` — PTY terminal sessions (spawn, I/O, resize, scrollback)
- `hort/targets.py` — Target registry (multi-machine management)
- `hort/models.py` — Pydantic models (strict types, frozen where appropriate)
- `hort/screen.py` — Window screenshot capture (Quartz → PIL → JPEG)
- `hort/windows.py` — Window listing/filtering (Quartz + SkyLight)
- `hort/input.py` — Input simulation (mouse/keyboard via Quartz CGEvent + AX API)
- `hort/spaces.py` — macOS Spaces detection and switching (SkyLight)
- `hort/network.py` — LAN IP detection, QR code generation
- `hort/cert.py` — Self-signed TLS certificate generation
- `hort/ext/` — Extension system (types, manifest, registry)
- `hort/containers/` — Container management (base ABC, Docker provider, registry)
- `hort/extensions/core/` — Built-in platform extensions (macOS, Linux, LAN/Cloud connectors)
- `hort/access/` — Remote access proxy server (Azure deployment, tunnel protocol, token auth)
- `hort/access/docker-compose.yml` — Docker Compose for local dev and Azure deployment
- `hort/static/index.html` — Quasar/Vue 3 mobile-first UI
- `hort/static/vendor/` — Pre-compiled Vue 3, Quasar, xterm.js, Plotly.js, Material Icons

## Communication Protocol

All control communication flows through a single JSON WebSocket per session:

1. `POST /api/session` → `{session_id}`
2. `WebSocket /ws/control/{session_id}` — JSON control messages
3. `WebSocket /ws/stream/{session_id}` — binary JPEG frames
4. `WebSocket /ws/terminal/{terminal_id}` — binary PTY I/O

## Testing

**Always prefer Playwright for UI testing** — it runs headless and produces screenshots.

```bash
# Unit tests (100% coverage required)
poetry run pytest tests/ --cov=hort

# Playwright UI tests (integration, skipped by default)
poetry run pytest tests/test_ui_playwright.py -m integration

# Quick Playwright smoke test (inline)
LLMING_AUTH_SECRET=openhort-dev poetry run python -c "
from playwright.sync_api import sync_playwright
# ... start server, open page, take screenshot
"
```

Note: xterm.js keyboard input doesn't work in headless Playwright (canvas-based rendering).
Use Playwright for visual verification; use the Chrome MCP tools or real browser for interactive terminal testing.

## Guidelines

- [UX Guidelines](docs/ux-guidelines.md) — interaction model, fit modes, panning rules, resolution strategy
- [Extension System](docs/extensions.md) — plugin architecture, provider interfaces, creating extensions
- [Llmings](docs/llmings.md) — panel architecture, shared components, plugin lifecycle
- [Access Server](docs/access-server.md) — remote proxy, Azure deployment, tunnel protocol
- [Container Environments](docs/containers.md) — Docker/Azure container management, preview panel

## Critical Rules

- **NEVER block the async event loop.** Every subprocess call, Docker exec, provider method, file I/O, and network call MUST run in a thread executor (`await _run_sync(fn)`) or use native async I/O (`add_reader`, `asyncio.open_unix_connection`). A single blocking call on the main thread can hang the entire server and prevent clean shutdown (uvicorn --reload). No exceptions.
- **NEVER use `lsof -ti :PORT | xargs kill`** — this kills Docker containers. Always kill by process name: `pgrep -f "uvicorn hort.app" | xargs kill -9`

## Quality Standards

- 100% test coverage (`pytest --cov=hort`, excludes `hort/extensions/` and `hort/terminal.py` which are integration-tested)
- mypy strict on `hort/` (tests excluded)
- Pydantic v2 for all data models
- OS-level Quartz wrappers isolated behind `_raw_*` functions for testability

## Running

```bash
poetry run python run.py
```

Requires Screen Recording permission for the terminal app in System Settings (macOS).

Dev mode (`--dev` or `LLMING_DEV=1`) enables:
- `uvicorn --reload` on HTTP port 8940 — auto-restarts on Python changes in `hort/`
- `--timeout-graceful-shutdown 5` — force-kills worker after 5s on reload (prevents deadlocks)
- Client-side hot-reload — browser refreshes on `index.html` changes
- HTTPS on port 8950 via nginx proxy (`tools/local-https/`, run once with `docker compose up -d`)
- The proxy shows "Server restarting..." during reloads instead of connection errors

**NEVER use `lsof -ti :8940 | xargs kill -9`** — this kills Docker containers connected to that port, tearing down HTTPS proxy and Linux containers. ALWAYS kill by process name:

### Restarting the server
```bash
pgrep -f "uvicorn hort.app" | xargs kill -9
sleep 3
poetry run python run.py
```
If the port is still busy after 3 seconds, wait longer — do NOT fall back to killing by port.

### If Docker was killed (HTTPS proxy / Linux container down)
```bash
open -a "Docker"                                          # Start Docker Desktop
# Wait for Docker to be ready, then:
cd tools/local-https && docker compose up -d && cd -      # HTTPS proxy
docker start openhort-linux-desktop                       # Linux container
pkill -f "uvicorn hort.app" && sleep 2 && poetry run python run.py  # Restart server to rediscover targets
```

## Logging

Rotating log file at `logs/openhort.log` (5 MB, 3 backups). Captures startup, shutdown, and any deadlocks during hot-reload. Check this file when the server hangs:
```bash
tail -50 logs/openhort.log
```

## Access Server (Cloud Proxy)

Remote access via `https://openhort-access.azurewebsites.net`. See [docs/access-server.md](docs/access-server.md) for full details.

### Deploying
```bash
bash scripts/deploy-access.sh
# Verify: curl https://openhort-access.azurewebsites.net/cfversion
```

### Critical Azure Findings
- **WS message size limit:** Azure silently drops WebSocket messages > ~64KB. Tunnel client chunks large responses into 32KB messages.
- **Image caching:** `latest` tag doesn't force re-pull. Always use versioned tags (deploy script does this automatically).
- **Content-Length:** Must be removed from proxied response headers after `<base>` tag injection (changes body size).
- **Quasar UMD:** Scripts MUST be in `<body>`, not `<head>` — Quasar needs DOM to exist at load time.
- **Persistent storage:** FileStore JSON is ephemeral. Mount `/data/` volume. Admin user created by entrypoint only if store missing.

### Local Testing
```bash
docker compose -f hort/access/docker-compose.yml up -d   # Start access server on port 8400
poetry run python -m hort.access.tunnel_client --server=http://localhost:8400 --key=<KEY> --local=http://localhost:8940
```

## Environment

Set `LLMING_AUTH_SECRET` in `.env` (already configured for dev).
