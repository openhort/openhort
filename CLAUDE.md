# openhort

Remote window viewer — watch and control your machine from your phone/tablet.

## Terminology

- **Llming** — an extension unit (plugin). The building block of the system.
- **Soul** (`SOUL.md`) — what an Llming knows and how it behaves. Markdown file with feature-gated sections.
- **Powers** — what an Llming can do. MCP tools exposed via `MCPMixin`.
- **Circuits** — visual flow editor for wiring Llmings, triggers, and actions into automated workflows (`/hortmap`).

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
- `hort/screen.py` — Window + desktop screenshot capture (Quartz → PIL → JPEG, `DESKTOP_WINDOW_ID=-1` for full screen)
- `hort/windows.py` — Window listing/filtering (Quartz + SkyLight, includes virtual Desktop entry)
- `hort/thumbnailer.py` — Thumbnail rotation scheduler (fixed-bandwidth, one capture at a time)
- `hort/signals/` — Signal system (event bus, processors, triggers, watchers)
- `hort/hortmap/` — Circuits (visual flow editor, Drawflow UI at `/hortmap`)
- `hort/input.py` — Input simulation (mouse/keyboard via Quartz CGEvent + AX API)
- `hort/spaces.py` — macOS Spaces detection and switching (SkyLight)
- `hort/network.py` — LAN IP detection, QR code generation
- `hort/cert.py` — Self-signed TLS certificate generation
- `hort/ext/` — Extension system (types, manifest, registry)
- `hort/containers/` — Container management (base ABC, Docker provider, registry)
- `hort/ext/connectors.py` — Connector framework (ConnectorBase, CommandRegistry, ConnectorMixin)
- `hort/plugins.py` — Plugin lifecycle (discovery, loading, scheduler/connector startup, shutdown)
- `hort/extensions/core/` — Built-in platform extensions (macOS, Linux, LAN/Cloud/Telegram connectors)
- `hort/peer2peer/` — Reusable P2P hole punching library (STUN, signaling ABC, punch coordinator, UDP tunnel)
- `hort/extensions/core/peer2peer/` — P2P extension (Azure VM provisioning, connector commands, MCP tools)
- `hort/access/` — Remote access proxy server (Azure deployment, tunnel protocol, token auth)
- `hort/access/docker-compose.yml` — Docker Compose for local dev and Azure deployment
- `hort/static/index.html` — Quasar/Vue 3 mobile-first UI
- `hort/static/vendor/` — Pre-compiled Vue 3, Quasar, xterm.js, Plotly.js, Material Icons, Phosphor Icons, hort-ext.js, hort-widgets.js

## Communication Protocol

All control communication flows through a single JSON WebSocket per session:

1. `POST /api/session` → `{session_id}`
2. `WebSocket /ws/control/{session_id}` — JSON control messages
3. `WebSocket /ws/stream/{session_id}` — binary JPEG frames
4. `WebSocket /ws/terminal/{terminal_id}` — binary PTY I/O

## Testing

**Always prefer Playwright for UI testing** — it runs headless and produces screenshots.

**NEVER run the full test suite with `--cov=hort` or run tests in background (`run_in_background`).** Coverage instrumentation force-imports every module under `hort/`, which loads Quartz/pyobjc and the screen capture code. Autoreleased native `CFData` from `CGDataProviderCopyData` leaks 10-50 MB per frame and is invisible to Python's GC. A single `--cov=hort` run can consume 10+ GB of RAM; multiple stacked runs have crashed the entire system. Always run targeted tests instead:

```bash
# Run specific test files (PREFERRED — fast, safe)
poetry run pytest tests/test_foo.py -v

# Run the full suite WITHOUT coverage (if you must)
poetry run pytest tests/ -x -q --ignore=tests/test_ui_playwright.py

# Coverage only when explicitly requested by the user
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

## Documentation Strategy

**This file (CLAUDE.md)** contains compressed essential rules and quick-reference pointers. It is the single source of truth for AI assistants and must stay concise.

**`docs/`** contains detailed human-readable documentation (mkdocs-material, serves as HTML with search). The detail definitions live there and are LINKED from here — never duplicated.

**`docs/ai/`** contains AI-specific reference material (writing guides, conventions) that lives in the repo so it works on any machine. Not for humans, not in the mkdocs nav — just for AI context.

**Doc structure:**
- `docs/manual/guide/` — end-user pages (quickstart, config, cloud setup). Task-oriented, no jargon.
- `docs/manual/develop/` — extension developer docs (plugins, extensions, providers, platform support, etc.)
- `docs/manual/internals/` — core architecture, protocols, security, roadmap (coding agents)
- `docs/mkdocs.yml` — nav tree. New pages MUST be added here to appear in the built site.

**Rules:**
- CLAUDE.md = compressed rules + links. Never duplicate full docs content here.
- `docs/` = canonical detail. If CLAUDE.md and docs/ disagree, docs/ wins — update CLAUDE.md.
- New extension developer docs go in `docs/manual/develop/`.
- New core/internals docs go in `docs/manual/internals/`.
- When changing behavior, update docs/ first, then update the CLAUDE.md summary/link.
- Before adding content to CLAUDE.md, check if it already exists in docs/ and link instead.
- When writing documentation, follow [docs/manual/develop/docs-writing-guide.md](docs/manual/develop/docs-writing-guide.md) — mermaid diagrams, admonitions, code blocks, tabs, all mkdocs-material features with syntax.

## Guidelines

- [UX Guidelines](docs/manual/develop/ux-guidelines.md) — interaction model, fit modes, panning rules, resolution strategy
- [Plugin Ecosystem](docs/manual/develop/plugins.md) — plugin development guide, storage, scheduler, MCP, intents, widgets
- [Extension System](docs/manual/develop/extensions.md) — provider interfaces, manifest, registry, creating extensions
- [Linux Support](docs/manual/develop/linux-support.md) — native Linux provider, X11 tools, Docker deployment, P2P networking
- [Windows Support](docs/manual/develop/windows-support.md) — native Windows provider, Win32 API (ctypes), Azure VM testing
- [Cross-Platform Testing](docs/manual/develop/cross-platform-testing.md) — Azure VM provisioning, E2E testing, distribution strategy
- [Distribution & Installation](docs/manual/develop/distribution.md) — pipx/Docker/deb packaging, `hort setup` wizard, macOS .app bundle for Screen Recording
- [Client Apps](docs/manual/develop/client-apps.md) — native WebView wrappers (Android/iOS/macOS/Windows), thin shell principles, repo at `openhort-clients`
- [Llmings](docs/manual/develop/llmings.md) — panel architecture, shared components, plugin lifecycle
- [Access Server](docs/manual/develop/access-server.md) — remote proxy, Azure deployment, tunnel protocol
- [Container Environments](docs/manual/develop/containers.md) — Docker/Azure container management, preview panel
- [Agent Framework](docs/manual/index.md) — AI agent sandboxing, permissions, budget, multi-node orchestration
- [Screen Capture](docs/manual/develop/screen-capture.md) — per-window + desktop capture, viewport-based streaming, output resolution rules (no DPR!), resize strategy, VP8 considerations, zoom behavior
- [Memory Safety](docs/manual/develop/memory-safety.md) — CGImage native leaks, CGDataProviderCopyData autorelease trap, CGBitmapContext fix, WebSocket backpressure, asyncio buffer limits
- [MCP Bridge & Chat Backend](docs/manual/develop/mcp-servers.md#in-process-mcp-bridge) — extension MCP tools, tool namespacing, chat routing, SOUL.md prompt system
- [Peer-to-Peer](docs/manual/develop/peer2peer.md) — P2P hole punching library, STUN, signaling, UDP tunnel, Azure test VM
- [Telegram & Mini Apps](docs/manual/develop/telegram.md) — Bot API, Mini App WebView, WebRTC signaling, debugging
- [Docs Writing Guide](docs/manual/develop/docs-writing-guide.md) — mkdocs-material features, mermaid, admonitions, syntax reference
- [Wiring Model](docs/manual/internals/security/wiring-model.md) — two concepts (llmings + horts), connections, groups, direct wiring, visual editor, complete YAML reference
- [Llming Data Types](docs/manual/internals/protocols/llming-types.md) — universal Pydantic models (Mail, CalendarEvent, Metric, Record), broadcasts, risk levels, version compat, author verification
- [Information Flow Control](docs/manual/internals/security/flow-control.md) — taint labels, flow policies, isolation zones, parameter-level classification, nested Hort boundaries
- [Taint Tracking](docs/manual/internals/security/taint-tracking.md) — data model, label classifier, propagation rules, audit trail
- [Flow Policies & Zones](docs/manual/internals/security/flow-policies.md) — policy engine, zone isolation, auto-escalation, broadcast channels, simple/advanced config
- [Boundary Filters](docs/manual/internals/security/boundary-filters.md) — MCP filter chains, content inspection (regex/AI), container network egress filtering, DNS/IP/URL allowlists

## Critical Rules

- **NEVER run `git commit`.** Only the user commits.
- **NEVER use `alert()`, `confirm()`, or `prompt()`.** Always use `Quasar.Dialog.create()` — see [UX Guidelines: No JavaScript Dialogs](docs/manual/develop/ux-guidelines.md#no-javascript-dialogs).
- **OAuth callback is localhost-only.** Never serve `/auth/callback` via the cloud proxy — multi-tenant callback interception risk. Remote auth uses device code flow exclusively. See [Credentials docs](docs/manual/develop/mcp-servers.md#security-oauth-callback-restricted-to-localhost).
- **NEVER block the async event loop.** Every subprocess call, Docker exec, provider method, file I/O, and network call MUST run in a thread executor (`await _run_sync(fn)`) or use native async I/O (`add_reader`, `asyncio.open_unix_connection`). A single blocking call on the main thread can hang the entire server and prevent clean shutdown (uvicorn --reload). No exceptions.
- **NEVER use `lsof -ti :PORT | xargs kill`** — this kills Docker containers. Always kill by process name: `pgrep -f "uvicorn hort.app" | xargs kill -9`
- **NEVER load or start plugins at import time or in `create_app()`.** Plugin loading (`load_plugins_sync`), scheduler start, and connector start MUST happen exclusively in the FastAPI `on_event("startup")` handler. With uvicorn `--reload`, `create_app()` runs multiple times per module import — loading plugins there causes duplicate instances (e.g. multiple Telegram bots competing for the same token via `TelegramConflictError`). Clean shutdown via `stop_plugins()` in `on_event("shutdown")`.
- **NEVER use `asyncio.create_task` for deferred plugin startup.** Background tasks created in startup events get killed silently on `--reload`. Run plugin startup synchronously in the startup event instead.
- **ALWAYS release native macOS resources promptly.** `CGWindowListCreateImage` returns Core Foundation objects whose pixel buffers (10-50 MB each) are NOT tracked by Python's GC. **NEVER use `CGDataProviderCopyData()` on background threads** — it creates autoreleased CFData that never drains (leaked 17 GB in production). Use `CGBitmapContextCreate` + `CGContextDrawImage` to render into a Python-owned `bytearray` instead. Call `pil_image.close()` after encoding. Do NOT call `CFRelease()` directly — pyobjc owns the ref and double-release causes SIGABRT. See [Memory Safety](docs/manual/develop/memory-safety.md).
- **Desktop capture uses `CGDisplayCreateImage(CGMainDisplayID())`** — captures the main display only (not all monitors). Window_id `-1` (`DESKTOP_WINDOW_ID`) triggers this path. Desktop bounds come from `CGDisplayBounds()` for correct coordinate mapping. Input clicks go to absolute screen coordinates (no app activation).
- **Status bar IPC uses a shared key file.** Both the plugin and status bar read/write `~/.hort/statusbar.key`. Whoever starts first creates it; either side rotates when it's older than 24 h. The status bar sends the key as `X-Hort-Key` header on every request. The plugin's `/verify` endpoint validates with `secrets.compare_digest`. Atomic writes (tempfile + rename) prevent corruption from concurrent starts. See [Threat Model](docs/manual/internals/security/threat-model.md).

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
- **Binary proxy corruption:** Response bodies MUST stay as raw bytes (`body_bytes`). Decoding as UTF-8 corrupts fonts/images.
- **Image caching:** `latest` tag doesn't force re-pull. Always use versioned tags (deploy script does this automatically).
- **Content-Length:** Must be removed from proxied response headers after `<base>` tag injection (changes body size).
- **Quasar UMD:** Scripts MUST be in `<body>`, not `<head>` — Quasar needs DOM to exist at load time.
- **Persistent storage:** FileStore JSON is ephemeral. Mount `/data/` volume. Admin user created by entrypoint only if store missing.
- **Service worker:** Never register SW when proxied (`_basePath` set). Old cached SWs must be manually unregistered.
- **Plugin scripts:** Script URLs from `/api/plugins` must be prefixed with `basePath` for proxy routing.

### Plugin Architecture Rules
- **activate() always called** — even without config (receives `{}`). Initialize all instance vars here.
- **Live data in memory** — never write volatile metrics to disk. Use `self._latest`, `self._history`.
- **Disk for persistence only** — clipboard entries, user config, saved tokens.
- **No locks** — `LocalBlobStore` uses atomic file writes (`tempfile + os.replace`). No threading.Lock (deadlocks on hot-reload).
- **Thumbnail data flow:** Python `get_status()` → JS `_feedStore()` → `renderThumbnail()` → canvas → grid card.

### Plugin Lifecycle (startup/shutdown)
```
create_app()          → setup_plugins() discovers manifests, registers API routes (NO loading)
on_event("startup")   → load_plugins_sync() → start_plugins() → schedulers → connectors
on_event("shutdown")  → stop_plugins() → stop connectors → stop schedulers
```
This ensures each plugin is loaded exactly once and cleaned up on shutdown. With `--reload`, the old worker shuts down cleanly before the new one starts.

### Connector Framework
- **Files:** `hort/ext/connectors.py` (framework), `hort/extensions/core/telegram_connector/` (Telegram impl)
- **Classes:** `ConnectorBase` (abstract connector), `ConnectorMixin` (plugin commands), `CommandRegistry` (routing), `ConnectorResponse` (multi-format response)
- **System commands** (help, status, link, etc.) defined in the connector provider — plugins CANNOT override them
- **Plugin commands** registered via `ConnectorMixin.get_connector_commands()` on any `PluginBase` subclass
- **Response fallback:** `render_text()` picks best format for the connector (HTML → Markdown → plain text). `send_response()` auto-falls back to plain text on parse failure.
- **Telegram specifics:**
  - Use **HTML** (`<b>bold</b>`) not Markdown v1 (`*bold*`) — Markdown v1 breaks on em-dashes and `/` characters
  - `delete_webhook(drop_pending_updates=True)` before polling to claim exclusive access (prevents conflicts on restart)
  - Retry logic (5 attempts with backoff) for `TelegramConflictError`
  - Requires `TELEGRAM_BOT_TOKEN` env var; ACL via `allowed_users` config
- **UI panels:** Each connector has `static/panel.js` extending `HortExtension`, using `connector-panel` CSS classes (same pattern as LAN/Cloud panels)

### Debugging Stale Processes
When the server behaves unexpectedly (old code running, Telegram conflicts, port busy):
```bash
lsof -ti :8940                                    # Find ALL processes on the port (including Docker, orphaned workers)
ps -p <PID> -o pid,lstart,command                 # Check when each process started
pgrep -af "python.*telegram\|python.*hort"        # Find any hort-related Python processes
```
`pgrep -f "uvicorn"` misses multiprocessing spawn children. Always verify with `lsof` and check start times.

### Local Testing
```bash
docker compose -f hort/access/docker-compose.yml up -d   # Start access server on port 8400
poetry run python -m hort.access.tunnel_client --server=http://localhost:8400 --key=<KEY> --local=http://localhost:8940
```

## Sandbox Sessions (hort/sandbox/)

Core infrastructure for isolated Docker execution environments with session lifecycle, MCP server support, and automatic cleanup. See [sandbox docs](docs/manual/develop/sandbox-sessions.md) and [MCP docs](docs/manual/develop/mcp-servers.md).

Key files: `hort/sandbox/{session,reaper,mcp,mcp_proxy}.py`
Tests: `poetry run pytest tests/test_sandbox*.py -v`

## LLM Framework (hort/llm/)

Provider interfaces and conversation management for both CLI-executed LLMs (Claude Code, Codex) and API-based LLMs (Anthropic, OpenAI, Mistral). API providers store/refetch conversation history from a unified store with timeout-based cleanup.

Key files: `hort/llm/{base,cli_provider,api_provider,history}.py`
Tests: `poetry run pytest tests/test_llm*.py -v`

## Claude Code Extension (hort/extensions/llms/claude_code/)

First LLM extension — Claude Code CLI. Extends `CLIProvider`. Others (Mistral, Gemini, Codex) follow the same pattern.

```bash
# Local chat
poetry run python -m hort.extensions.llms.claude_code

# Container chat (sandboxed, auth from macOS Keychain)
poetry run python -m hort.extensions.llms.claude_code --container

# Container with resource limits + MCP servers
poetry run python -m hort.extensions.llms.claude_code -c --memory 512m --cpus 2 \
  --mcp "fs=npx -y @anthropic/mcp-filesystem /tmp"

# Session management
poetry run python -m hort.extensions.llms.claude_code --list-sessions
poetry run python -m hort.extensions.llms.claude_code -c --session <id>  # resume
poetry run python -m hort.extensions.llms.claude_code --cleanup
```

Key files: `hort/extensions/llms/claude_code/{provider,chat,stream,typewriter,auth}.py`
Tests: `poetry run pytest hort/extensions/llms/claude_code/tests/ -v`

## Documentation Site

Pre-built mkdocs-material site served at `/guide/` from the openhort server. Also accessible via the cloud proxy at `/proxy/{host_id}/guide/`.

```bash
# Rebuild after editing docs
cd docs && poetry run mkdocs build -f mkdocs.yml

# Live preview with hot-reload
cd docs && poetry run mkdocs serve -f mkdocs.yml

# Served automatically by openhort at /guide/ (if built)
```

Config: `docs/mkdocs.yml`
Source: `docs/manual/`
Output: `docs/_site/` (gitignored)

## Environment

Set `LLMING_AUTH_SECRET` in `.env` (already configured for dev).
