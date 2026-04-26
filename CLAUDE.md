# openhort

Remote window viewer — watch and control your machine from your phone/tablet.

## Terminology

- **Llming** — an extension unit. The universal building block. Has up to five parts: Soul, Powers, Pulse, Cards, Envoy. Server class: `Llming` (`hort/llming/base.py`). Client class: `LlmingClient` (`hort/static/vendor/hort-ext.js`). All llming code lives in `llmings/` (separate from the `hort/` framework package). Each llming runs in its own subprocess.
- **Soul** (`SOUL.md`) — what a Llming knows and how it behaves. Markdown file with feature-gated sections. Injected into the AI system prompt.
- **Powers** — what a Llming can do. Defined with `@power` decorator, auto-routed by the framework. Every power is an MCP tool by default (`mcp=False` to hide). Input/output are Pydantic models (`PowerInput`/`PowerOutput`). `PowerOutput` uses HTTP status codes (200/403/404/500). No manual `get_powers()` or `execute_power()` dispatch needed.
- **Pulse** — named channel events. Push-only (`self.emit("channel", data)`), subscribe with `@pulse("channel")` decorator or `self.channels["channel"].subscribe(handler)` at runtime. `get_pulse()` exists for UI thumbnail rendering only — NOT for cross-llming data. Built-in tick channels: `tick:10hz`, `tick:1hz`, `tick:5s`. Lifecycle events: `llming:started`, `llming:stopped`.
- **Cards** — how a Llming looks. Grid thumbnails, detail panels, widgets, float windows.
- **Envoy** — the Llming's execution agent inside a sub-hort (container/VM/remote machine). Runs locally inside the isolation boundary. Handles MCP (stdio + SSE, SDK-agnostic), process management, credential provisioning, and streaming output. Speaks H2H protocol over stdio/TCP. Works with any MCP client (Claude Code, OpenAI, Anthropic SDK). openhort can also run as a standalone MCP reverse proxy with policy enforcement. See [Envoy Architecture](docs/manual/internals/envoy-architecture.md).
- **Circuits** — visual flow editor for wiring Llmings, triggers, and actions into automated workflows (`/hortmap`).
- **Neighbors** — horts at the same level that can wire bidirectionally (first connection wins).

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
- `hort/llming/` — Llming framework: `base.py` (Llming class), `decorators.py` (`@power`, `@pulse`, `@on_ready`), `models.py` (`PowerInput`, `PowerOutput`, `PulseEvent`), `handles.py` (self.llmings, self.vaults, self.channels, `vault_ref` descriptor), `llm_executor.py` (LlmExecutor base for LLM providers), `powers.py`, `pulse.py` (named channel bus), `bus.py` (MessageBus + power_catalog)
- `hort/ext/vue_loader.py` — Vue SFC compiler: `<script setup>` support, import rewriting (vue/quasar/llming), `vaultRef` injection, card + app modes
- `hort/lifecycle/` — Subprocess isolation: `manager.py` (ManagedProcess), `worker.py` (Worker base), `runner.py` (llming subprocess entry point), `llming_process.py` (LlmingProcess + LlmingProxy), `ipc_protocol.py` (IPC message types)
- `hort/envoy/` — Envoy agent (MCP stdio server, control channel, host client)
- `hort/ext/` — Framework internals: `registry.py` (extension discovery/loading), `manifest.py`, `scheduler.py`, `store.py`, `claude_auth.py` (cross-platform credential extraction)
- `hort/containers/` — Container management (base ABC, Docker provider, registry)
- `hort/ext/chat_backend.py` — Chat backend (routes messages to LLM executor, MCP bridge)
- `hort/commands/` — WS command modules (llmings, config, cam, wire, debug, sources)
- `hort/plugins.py` — Llming lifecycle (discovery, loading, @pulse wiring, non-blocking startup, tick channels)
- `llmings/` — ALL llming implementations (separate package, NOT part of hort). Main process never imports from here.
- `llmings/core/` — Built-in llmings (system-monitor, telegram, hue-bridge, peer2peer, etc.)
- `llmings/llms/` — LLM executor llmings (claude_code, llming_models_ext)
- `hort/peer2peer/` — Reusable P2P hole punching library (STUN, signaling ABC, punch coordinator, UDP tunnel)
- `hort/access/` — Remote access proxy server (Azure deployment, tunnel protocol, token auth)
- `hort/access/docker-compose.yml` — Docker Compose for local dev and Azure deployment
- `hort/static/index.html` — Quasar/Vue 3 mobile-first UI
- `hort/static/vendor/` — Pre-compiled Vue 3, Quasar, xterm.js, Plotly.js, Material Icons, Phosphor Icons, hort-ext.js (`LlmingClient` base, `vaultRef` push, vault watcher registry), hort-widgets.js, hort-llmings-ui.js, hort-demo.js (demo mode runtime)
- `sample-data/` — Shared sample data for demo mode (accessible via `ctx.shared()` in demo.js)

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
- `docs/manual/develop/` — llming developer docs (creating llmings, MCP, containers, platform support, etc.)
- `docs/manual/develop/` → "Core Llmings" subsection — docs for built-in llmings (Code Watch, Wire Chat, Claude Code, P2P, Telegram)
- `docs/manual/internals/` — core architecture, protocols, security, roadmap (coding agents)
- `docs/mkdocs.yml` — nav tree. New pages MUST be added here to appear in the built site.

**Rules:**
- CLAUDE.md = compressed rules + links. Never duplicate full docs content here.
- `docs/` = canonical detail. If CLAUDE.md and docs/ disagree, docs/ wins — update CLAUDE.md.
- New llming developer docs go in `docs/manual/develop/`.
- New core llming docs go in `docs/manual/develop/` under "Core Llmings" nav section.
- New core/internals docs go in `docs/manual/internals/`.
- When changing behavior, update docs/ first, then update the CLAUDE.md summary/link.
- Before adding content to CLAUDE.md, check if it already exists in docs/ and link instead.
- When writing documentation, follow [docs/manual/develop/docs-writing-guide.md](docs/manual/develop/docs-writing-guide.md) — mermaid diagrams, admonitions, code blocks, tabs, all mkdocs-material features with syntax.

## Guidelines

- **[Coding Guidelines](docs/ai/coding-guidelines.md)** — MUST follow: no private access, no if/elif dispatch, config over hardcoding, WS-first, error handling
- [UI Concepts](docs/manual/internals/ui-concepts.md) — widget home screen, desktops, spatial hierarchy, IndexedDB layout persistence, widget data model
- [URL Parameters](docs/manual/internals/url-params.md) — `?desktop=N`, `?app=NAME`, `?mode=window|fullscreen|widget` deep-link contract
- [UX Guidelines](docs/manual/develop/ux-guidelines.md) — interaction model, fit modes, panning rules, resolution strategy
- [Llming Development](docs/manual/develop/plugins.md) — creating llmings, storage, scheduler, MCP, intents, widgets
- [Llming System](docs/manual/develop/extensions.md) — provider interfaces, manifest, registry, creating llmings
- [Linux Support](docs/manual/develop/linux-support.md) — native Linux provider, X11 tools, Docker deployment, P2P networking
- [Windows Support](docs/manual/develop/windows-support.md) — native Windows provider, Win32 API (ctypes), Azure VM testing
- [Cross-Platform Testing](docs/manual/develop/cross-platform-testing.md) — Azure VM provisioning, E2E testing, distribution strategy
- [Distribution & Installation](docs/manual/develop/distribution.md) — pipx/Docker/deb packaging, `hort setup` wizard, macOS .app bundle for Screen Recording
- [Client Apps](docs/manual/develop/client-apps.md) — native WebView wrappers, deep linking (`openhort://`), QR scanner, native bridge protocol (`nav.update`), P2P auto-reconnect, theme delegation
- [SPA Navigation](docs/manual/develop/spa-navigation.md) — History API router, unified toolbar, clean URLs (`/llming/{provider}/{name}/{sub}`), llming sub-pages, back-button guard, deep-link reload, server catch-all
- [Multi-Instance Isolation](docs/manual/develop/multi-instance.md) — per-instance data dirs, P2P port isolation, zero cross-instance interference
- [Llming UI](docs/manual/develop/llmings.md) — panel architecture, shared components, llming lifecycle
- [Access Server](docs/manual/develop/access-server.md) — remote proxy, Azure deployment, tunnel protocol
- [Container Environments](docs/manual/develop/containers.md) — Docker/Azure container management, preview panel
- [Agent Framework](docs/manual/index.md) — AI agent sandboxing, permissions, budget, multi-node orchestration
- [Screen Capture](docs/manual/develop/screen-capture.md) — per-window + desktop capture, viewport-based streaming, output resolution rules (no DPR!), resize strategy, VP8 considerations, zoom behavior
- [Memory Safety](docs/manual/develop/memory-safety.md) — CGImage native leaks, CGDataProviderCopyData autorelease trap, CGBitmapContext fix, WebSocket backpressure, asyncio buffer limits, aiortc zombie session cleanup
- [MCP Bridge & Chat Backend](docs/manual/develop/mcp-servers.md#in-process-mcp-bridge) — llming MCP tools, tool namespacing, chat routing, SOUL.md prompt system
- [Chat Debug API](docs/manual/internals/chat-debug-api.md) — send messages to AI, inspect tool calls, diagnose failures
- [Envoy Architecture](docs/manual/internals/envoy-architecture.md) — execution agent inside sub-horts, MCP stdio, process management, credential provisioning, H2H wire channels
- [Process Lifecycle](docs/manual/internals/process-lifecycle.md) — managed subprocesses, PID files, hot-reload survival, orphan cleanup, IPC protocol
- [Peer-to-Peer](docs/manual/develop/peer2peer.md) — P2P hole punching library, STUN, signaling, UDP tunnel, Azure test VM
- [Telegram & Mini Apps](docs/manual/develop/telegram.md) — Bot API, Mini App WebView, WebRTC signaling, debugging
- [Docs Writing Guide](docs/manual/develop/docs-writing-guide.md) — mkdocs-material features, mermaid, admonitions, syntax reference
- [Wiring Model](docs/manual/internals/security/wiring-model.md) — two concepts (llmings + horts), connections, groups, direct wiring, visual editor, complete YAML reference
- [Llming Data Types](docs/manual/internals/protocols/llming-types.md) — universal Pydantic models (Mail, CalendarEvent, Metric, Record), broadcasts, risk levels, version compat, author verification
- [Information Flow Control](docs/manual/internals/security/flow-control.md) — taint labels, flow policies, isolation zones, parameter-level classification, nested Hort boundaries
- [Taint Tracking](docs/manual/internals/security/taint-tracking.md) — data model, label classifier, propagation rules, audit trail
- [Flow Policies & Zones](docs/manual/internals/security/flow-policies.md) — policy engine, zone isolation, auto-escalation, broadcast channels, simple/advanced config
- [Boundary Filters](docs/manual/internals/security/boundary-filters.md) — MCP filter chains, content inspection (regex/AI), container network egress filtering, DNS/IP/URL allowlists
- [H2H Protocol](docs/manual/internals/protocols/h2h-protocol.md) — hort-to-hort communication, transport-agnostic (stdio/HTTP/socket), tree routing, wire permissions (channels/direction/tools/CLI/filters), neighbor horts, constellation examples
- [Credential Provisioning](docs/manual/internals/security/credential-provisioning.md) — downward-only credential flow, OS credential stores (macOS/Linux/Windows), apiKeyHelper pattern, container injection, rotation, threat mitigations
- [Llming Anatomy](docs/manual/internals/llming-anatomy.md) — the five parts (Soul, Powers, Pulse, Cards, Envoy), manifest schema, composition, permission unification
- [Claude Code Integration](docs/manual/develop/claude-code-integration.md) — envoy container lifecycle, cross-platform credentials (Keychain/libsecret/CredMan), apiKeyHelper pattern, MCP bridge, session management, CLI flags
- [Group Isolation](docs/manual/internals/security/group-isolation.md) — colored groups, 4 relation types (isolated/mutual/reads/delegates), dual-layer enforcement (Soul + MCP bridge), auto-generated Soul instructions, delegation mechanism
- [Unified Access](docs/manual/internals/security/unified-access.md) — uphid, device_uid, pairing tokens, share links, guest access, hub device selector
- [Error Handling](docs/manual/internals/security/error-handling.md) — no internal errors to users, container lifecycle, shutdown cleanup

## Critical Rules

- **NEVER hardcode commands in connectors.** Every user-facing command MUST be a Power on a llming (e.g. `/hort` commands belong on `hort-chief`, not in the Telegram or Wire connector code). Connectors are pure transport — they route commands to llmings via the CommandRegistry. The only exceptions are the framework-level system commands (help, start, link, status, targets) defined in `hort/ext/connectors.py`.
- **NEVER claim the server is working without verifying in a real browser.** curl checks are NOT sufficient. Use Playwright headless to load the dashboard, verify WebSocket connects, thumbnails render, and pages navigate. At minimum: take a screenshot of the main grid showing live thumbnails. If Playwright is unavailable, use Chrome MCP tools. API-only checks (curl, httpie) do NOT verify the frontend — the SPA may fail to load, WebSockets may not connect, or Cards JS may error silently.
- **NEVER commit personal info, credentials, or identifiable data.** No real usernames, email addresses, API keys, tokens, registry hostnames, or organization names in code, config examples, docs, or test fixtures. Use generic placeholders (`alice_dev`, `user@example.com`, `yourregistry.azurecr.io`). The only exception is the LICENSE file copyright.
- **NEVER expose internal errors to users.** Stack traces, docker commands, container IDs, file paths, Python exceptions — NONE of this may ever appear in Telegram messages, web chat responses, API responses to unauthenticated clients, or any user-facing channel. Catch all exceptions and return safe generic messages ("Something went wrong. Try again."). Full details go to logs only. See [Error Handling](docs/manual/internals/security/error-handling.md).
- **Sandbox containers run until hort stops.** Containers are created on first use and persist across messages. On `hort stop` or status bar quit, ALL sandbox containers (`ohsb-*`) are stopped and removed. On `hort start`, orphaned containers from crashes are cleaned up. Never create containers eagerly at startup.
- **NEVER run `git commit`.** Only the user commits.
- **NEVER use `alert()`, `confirm()`, or `prompt()`.** Always use `Quasar.Dialog.create()` — see [UX Guidelines: No JavaScript Dialogs](docs/manual/develop/ux-guidelines.md#no-javascript-dialogs).
- **OAuth callback is localhost-only.** Never serve `/auth/callback` via the cloud proxy — multi-tenant callback interception risk. Remote auth uses device code flow exclusively. See [Credentials docs](docs/manual/develop/mcp-servers.md#security-oauth-callback-restricted-to-localhost).
- **NEVER block the async event loop.** Every subprocess call, Docker exec, provider method, file I/O, and network call MUST run in a thread executor (`await _run_sync(fn)`) or use native async I/O (`add_reader`, `asyncio.open_unix_connection`). A single blocking call on the main thread can hang the entire server and prevent clean shutdown (uvicorn --reload). No exceptions.
- **NEVER use `lsof -ti :PORT | xargs kill`** — this kills Docker containers. Always kill by process name: `pgrep -f "uvicorn hort.app" | xargs kill -9`
- **NEVER load or start llmings at import time or in `create_app()`.** Llming loading (`load_llmings_sync`), scheduler start, and connector start MUST happen exclusively in the FastAPI `on_event("startup")` handler. With uvicorn `--reload`, `create_app()` runs multiple times per module import — loading llmings there causes duplicate instances (e.g. multiple Telegram bots competing for the same token via `TelegramConflictError`). Clean shutdown via `stop_llmings()` in `on_event("shutdown")`.
- **ALL llmings run in subprocesses.** No llming code runs in the main process. The main process is a pure router — it reads manifests, spawns subprocesses, and proxies Powers/Pulses/Storage over IPC. This prevents community llmings from accessing credentials, other llmings' memory, or framework internals. See [Llming Isolation](docs/manual/internals/llming-isolation.md).
- **NEVER run background tasks inside the uvicorn worker.** Telegram polling, camera discovery, and other long-lived tasks MUST run in the llming's subprocess (which is separate from the main process). See [Process Lifecycle](docs/manual/internals/process-lifecycle.md).
- **NEVER use `asyncio.create_task` for deferred llming startup.** Background tasks created in startup events get killed silently on `--reload`. Run llming startup synchronously in the startup event instead.
- **ALWAYS release native macOS resources promptly.** `CGWindowListCreateImage` returns Core Foundation objects whose pixel buffers (10-50 MB each) are NOT tracked by Python's GC. **Every capture MUST be wrapped in `objc.autorelease_pool()`** — use `CGDataProviderCopyData` inside the pool (<2 MB/frame leak). **NEVER use `CGBitmapContextCreate`** for pixel extraction — its internal decompression cache leaks ~34 MB/frame and cannot be released by Python. Call `del cg_image` immediately after conversion and `pil_image.close()` after encoding. Do NOT call `CFRelease()` directly — pyobjc owns the ref and double-release causes SIGABRT. See [Memory Safety](docs/manual/develop/memory-safety.md).
- **Desktop capture uses `CGDisplayCreateImage(CGMainDisplayID())`** — captures the main display only (not all monitors). Window_id `-1` (`DESKTOP_WINDOW_ID`) triggers this path. Desktop bounds come from `CGDisplayBounds()` for correct coordinate mapping. Input clicks go to absolute screen coordinates (no app activation).
- **Status bar IPC uses a shared key file.** Both the llming and status bar read/write `~/.hort/statusbar.key`. Whoever starts first creates it; either side rotates when it's older than 24 h. The status bar sends the key as `X-Hort-Key` header on every request. The plugin's `/verify` endpoint validates with `secrets.compare_digest`. Atomic writes (tempfile + rename) prevent corruption from concurrent starts. See [Threat Model](docs/manual/internals/security/threat-model.md).

- **Claude Code CLI: `--mcp-config` is variadic.** The `--mcp-config <configs...>` flag consumes all following positional args. The user message MUST come after a `--` separator: `claude -p --mcp-config config.json -- "message"`. Without `--`, the message is consumed as a config file path → exit code 1.
- **Claude Code MCP: session-sticky failures.** If an MCP server connection fails during session init, Claude Code marks it as `"status": "failed"` in the session file. Resuming that session (`--resume`) keeps it failed — it never retries. The only fix is a new session (no `--resume`).

## Quality Standards

- 100% test coverage (`pytest --cov=hort`, excludes `llmings/` and `hort/terminal.py` which are integration-tested)
- mypy strict on `hort/` (tests excluded)
- Pydantic v2 for all data models
- OS-level Quartz wrappers isolated behind `_raw_*` functions for testability

## CLI

```bash
hort                    # show logo + help hint
hort start              # start server (production)
hort start --dev        # start server (dev mode, auto-reload)
hort stop               # stop running server
hort status             # server status + system info
hort llmings            # list all installed llmings
hort topology           # show hort topology tree
hort config             # show hort-config.yaml
hort config agent       # show specific config section
hort watch              # list active code sessions
hort watch claude       # create + attach tmux session (runs claude)
hort watch clauded      # runs claude --dangerously-skip-permissions
hort watch shell        # just a shell
hort watch read <name>  # read session output
hort watch send <name> "text" # send text to session
hort watch stop <name>  # kill session
hort interactive        # interactive REPL mode
```

Install: `pip install -e .` or `pipx install .` puts `hort` on PATH.

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

## Hub (Cloud Proxy + P2P Relay)

Unified Cloudflare Worker at `https://hub.openhort.ai`. Combines the access proxy and P2P relay into one deployment. See [docs/access-server.md](docs/access-server.md) for full details.

Source: `www_openhort_ai/workers/hub/` (index.js, tunnel.js, relay.js, auth.js)

### Deploying
```bash
cd www_openhort_ai/workers/hub
source ../.env
CLOUDFLARE_API_TOKEN=$CLOUDFLARE_API_TOKEN npx wrangler deploy
# Verify: curl https://hub.openhort.ai/health
```

### Legacy Azure Deploying (deprecated)
```bash
bash scripts/deploy-access.sh
```

### Critical Azure Findings
- **WS message size limit:** Azure silently drops WebSocket messages > ~64KB. Tunnel client chunks large responses into 32KB messages.
- **Binary proxy corruption:** Response bodies MUST stay as raw bytes (`body_bytes`). Decoding as UTF-8 corrupts fonts/images.
- **Image caching:** `latest` tag doesn't force re-pull. Always use versioned tags (deploy script does this automatically).
- **Content-Length:** Must be removed from proxied response headers after `<base>` tag injection (changes body size).
- **Quasar UMD:** Scripts MUST be in `<body>`, not `<head>` — Quasar needs DOM to exist at load time.
- **Persistent storage:** FileStore JSON is ephemeral. Mount `/data/` volume. Admin user created by entrypoint only if store missing.
- **Service worker:** Never register SW when proxied (`_basePath` set). Old cached SWs must be manually unregistered.
- **Llming scripts:** Script URLs from `/api/llmings` must be prefixed with `basePath` for proxy routing.

### Llming API — Powers, Pulses, Storage

**Defining powers** — use `@power` decorator, no manual routing:
```python
from hort.llming import Llming, power, PowerOutput

class MyLlming(Llming):
    @power("get_metrics", description="Get system metrics")
    async def get_metrics(self) -> MetricsResponse:
        return MetricsResponse(cpu=42.0)

    @power("cpu", description="CPU usage", command="/cpu")
    async def cpu_command(self) -> str:
        return f"CPU: {self._cpu}%"

    @power("internal", description="Not for AI", mcp=False)
    async def internal(self) -> PowerOutput:
        return PowerOutput(code=200, message="done")
```

**Data models** — all cross-boundary data is typed and versioned:
- `PowerInput(version=1)` — power request parameters
- `PowerOutput(version=1, code=200)` — HTTP-like status codes (200/403/404/500), `.ok` property
- `PulseEvent(version=1)` — named channel event payloads
- All inherit from `LlmingData(version=1)`

**Pulse channels** — push-only named channels, subscribe with `@pulse`:
```python
@pulse("cpu_spike")
async def handle_spike(self, data: dict) -> None: ...

@pulse("tick:1hz")
async def poll(self, data: dict) -> None: ...

# Or at runtime:
self.channels["cpu_spike"].subscribe(self.handler)
```

**Cross-llming communication:**
```python
result = await self.llmings["system-monitor"].call("get_metrics")
data = await self.vaults["system-monitor"].read("latest_metrics")
catalog = await self.discover("system-monitor")
```

**Reactive vault bindings (vault_ref):**
```python
class Dashboard(Llming):
    cpu = vault_ref('system-monitor', 'state.cpu_percent', default=0)

    @cpu.on_change
    async def on_spike(self, value, old):
        if value > 90: await self.emit('cpu_alert', {'cpu': value})
```

**Storage one-liners:**
```python
self.vault.set("key", {"cpu": 42})
data = self.vault.get("key", default={"cpu": 0})
```

**Vue SFC cards** — `{name}.vue` files compiled at serve time. Standard `<script setup>`, import rewriting (vue/quasar/llming). `vaultRef('owner', 'path', default)` for push-based reactive bindings. Apps via `app.vue` or `app/index.vue`. See [Llming Dev Guide](docs/manual/develop/llming-dev-guide.md).

**Demo mode** — in-memory vault mock, per-llming `demo.js` simulation. Toggle via `POST /api/debug/demo/on`, 5 rapid logo clicks, or `HortDemo.toggle()`. Amber "DEMO MODE" banner when active. Components re-mount on toggle. `ctx.load(path)` for own static data, `ctx.shared(path)` for shared `sample-data/`.

**LlmExecutor** — base class for LLM providers (Claude Code, Codex, etc.). Session lifecycle: `create_session` → `send_message` → `end_session`. All are standard Powers callable by any llming.

### Llming Lifecycle (startup/shutdown)
```
create_app()          → setup_llmings() discovers manifests, registers API routes (NO loading)
on_event("startup")   → load_llmings_sync() → start_llmings():
                          1. Build @power handler maps
                          2. Wire @pulse subscriptions
                          3. Start scheduler jobs
                          4. Start connectors (background tasks)
                          5. Fire @on_ready handlers
                          6. Emit llming:started events
                          7. Start tick channels (tick:10hz, tick:1hz, tick:5s)
on_event("shutdown")  → stop_llmings() → emit llming:stopped → deactivate all
```
Startup must complete in <3s. Connector starts are non-blocking background tasks.

### Envoy (container execution)
- **MCP is always local** — Envoy runs inside the container as an MCP stdio server. No network hop for tool discovery.
- **Tools are dynamic** — host pushes current tool definitions before each LLM invocation. No caching, no stale state.
- **Credentials are ephemeral** — provisioned in-memory via the control channel. Never persisted to disk inside containers.
- **`hort/envoy/`** — Envoy server, protocol, and host client code.
### Subprocess Isolation
- See [Llming Isolation](docs/manual/internals/llming-isolation.md) — group-based process model, IPC protocol, runner, proxy
- See [Card API](docs/manual/develop/card-api.md) — push-based pulses, vault/scrolls/power access from JS

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

## LLM Executors (llmings/core/claude_code/, llmings/llms/)

LLM providers are standard llmings extending `LlmExecutor`. Session lifecycle: `create_session` → `send_message` → `end_session`. All are Powers — callable by any llming or connector.

**Claude Code** (`llmings/core/claude_code/`) — `ClaudeCodeExecutor(LlmExecutor)`. Wraps Claude Code CLI.
**llming-models** (`llmings/llms/llming_models_ext/`) — `LlmingModelsExecutor(LlmExecutor)`. Multi-provider SDK (Anthropic, OpenAI, Mistral).

Anyone can create a new LLM executor (e.g. Codex) by extending `LlmExecutor` and implementing `_send()`.

```bash
# CLI chat
poetry run python -m llmings.llms.claude_code
poetry run python -m llmings.llms.claude_code --container
```

Key files: `llmings/core/claude_code/{provider,auth,stream,typewriter}.py`, `llmings/llms/llming_models_ext/provider.py`
Tests: `poetry run pytest tests/test_llm_executor.py -v`

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

`TEST_ANTHROPIC_API_KEY` is available in `.env` for unit tests that need the Claude API. **Test-only, low-tier key.** NEVER use for production, containers, or user-facing features. Use `os.environ["TEST_ANTHROPIC_API_KEY"]` in tests.
