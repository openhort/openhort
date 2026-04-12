# Llming Development

!!! warning "This page is being rewritten"
    The content below describes the **legacy plugin system** (PluginBase, mixins).
    The current system uses the **unified Llming API** with `@power` decorators,
    typed models, and named pulse channels. See CLAUDE.md for the current API.

## Current Architecture (v3)

All llming code lives in `llmings/` (separate from `hort/` framework). Each llming runs in its own subprocess.

### Minimal Llming

```
llmings/core/my_llming/
  manifest.json
  __init__.py
  provider.py
  static/cards.js       # optional UI
  SOUL.md               # optional AI prompt
```

```python
# provider.py
from hort.llming import Llming, power, pulse, PowerOutput

class MyLlming(Llming):
    @power("get_status", description="Get current status")
    async def get_status(self) -> StatusResponse:
        return StatusResponse(value=42)

    @power("cpu", description="CPU usage", command="/cpu")
    async def cpu_command(self) -> str:
        return f"CPU: {self._cpu}%"

    @pulse("tick:1hz")
    async def poll(self, data: dict) -> None:
        self._cpu = get_cpu()
        self.save("latest", {"cpu": self._cpu})
```

### Key Concepts

- **`@power`** — declares a power (MCP tool by default, `mcp=False` to hide). No manual `get_powers()` or `execute_power()`.
- **`@pulse`** — subscribes to a named pulse channel. Built-in: `tick:10hz`, `tick:1hz`, `tick:5s`, `llming:started`, `llming:stopped`.
- **`@on_ready`** — fires when dependencies are loaded.
- **`PowerOutput(code=200)`** — HTTP status codes for responses.
- **`self.save/load`** — one-liner storage with defaults.
- **`self.llmings["name"].call()`** — cross-llming power calls.
- **`self.vaults["name"].read()`** — read other llmings' shared data.

---

## Legacy Plugin System (v1/v2)

!!! note "The content below describes the old system and is kept for reference during migration."

## Quick Start (Legacy)

### Minimal Backend Plugin

```
llmings/core/my_plugin/
  manifest.json
  __init__.py
  provider.py
```

**extension.json:**
```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "Does something useful",
  "provider": "core",
  "platforms": ["darwin", "linux"],
  "capabilities": ["monitor"],
  "entry_point": "provider:MyPlugin",
  "icon": "ph ph-gear"
}
```

**provider.py:**
```python
from hort.ext.plugin import PluginBase

class MyPlugin(PluginBase):
    def activate(self, config: dict) -> None:
        self.log.info("Plugin %s activated", self.plugin_id)

    def deactivate(self) -> None:
        self.log.info("Plugin %s deactivated", self.plugin_id)
```

### Minimal UI-Only Plugin

```
llmings/core/my_widget/
  extension.json
  __init__.py
  static/
    panel.js
```

**extension.json:**
```json
{
  "name": "my-widget",
  "version": "0.1.0",
  "description": "A dashboard widget",
  "provider": "core",
  "platforms": ["darwin", "linux"],
  "capabilities": ["ui"],
  "ui_script": "static/panel.js",
  "ui_widgets": ["my-widget-card"],
  "icon": "ph ph-chart-bar"
}
```

**static/panel.js:**
```javascript
class MyWidget extends HortExtension {
    static id = 'my-widget';
    static name = 'My Widget';
    static llmingTitle = 'My Widget';
    static llmingIcon = 'ph ph-chart-bar';
    static llmingDescription = 'A dashboard widget';

    setup(app, Quasar) {
        app.component('my-widget-card', {
            template: `
                <div data-plugin="my-widget">
                    <hort-stat-card label="CPU" value="42" unit="°C" icon="ph ph-thermometer" />
                </div>
            `,
        });
    }
}
HortExtension.register(MyWidget);
```

---

## Architecture

### Plugin Types

A plugin can be any combination of these roles:

| Role | Mixin / Base | What it does |
|---|---|---|
| **Backend** | `PluginBase` | Python logic, data processing |
| **UI** | `HortExtension` (JS) | Vue components, widgets |
| **Scheduler** | `ScheduledMixin` | Interval background jobs |
| **MCP Provider** | `MCPMixin` | AI tools via Model Context Protocol |
| **Document Provider** | `DocumentMixin` | Searchable docs for AI |
| **Intent Handler** | `IntentMixin` | Accept photos, GPS, files, text from phone |
| **Router** | `get_router()` | Custom FastAPI endpoints |
| **Connector** | (convention) | LAN/Cloud/etc. connection management |
| **Platform** | `PlatformProvider` | Window management (macOS, Linux, etc.) |
| **DB Backend** | `PluginStore` impl | Storage backend (file, MongoDB, blob) |

### Plugin Lifecycle

```
1. Discovery    — registry scans extensions/ directories, parses extension.json
2. Loading      — Python module imported, class instantiated
3. Context      — PluginContext injected (store, files, config, scheduler, logger)
4. Activation   — plugin.activate(config) called
5. Jobs         — scheduler starts interval jobs from manifest + get_jobs()
6. Runtime      — plugin responds to messages, intents, MCP calls
7. Deactivation — plugin.deactivate() called, scheduler stops, router unmounted
```

### Directory Layout

```
llmings/                    # Built-in extensions (shipped with package)
  core/
    <plugin_name>/
      extension.json                # Manifest (required)
      __init__.py                   # Python package marker
      provider.py                   # Entry point module (if backend)
      static/                       # Client-side assets (if UI)
        panel.js                    # HortExtension subclass
      tests/                        # Plugin-specific tests (optional)

~/.llmings/                 # User-installed extensions (future)
  <provider>/
    <plugin_name>/
      extension.json
      ...
```

---

## Manifest Reference (`extension.json`)

All fields except `name` are optional with sensible defaults.

### Core Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | (required) | Unique plugin ID (kebab-case) |
| `version` | string | `"0.0.0"` | Semantic version |
| `description` | string | `""` | Human-readable description |
| `provider` | string | `"core"` | Provider namespace |
| `platforms` | string[] | `["darwin","linux","win32"]` | Compatible platforms |
| `capabilities` | string[] | `[]` | Capability tags (e.g. `"monitor"`, `"mcp"`) |
| `entry_point` | string | `""` | Python class (`"module:ClassName"`) |
| `path` | string | `""` | Set by registry during discovery |

### Plugin Metadata

| Field | Type | Default | Description |
|---|---|---|---|
| `author` | string | `""` | Author name |
| `license` | string | `""` | License (e.g. `"MIT"`) |
| `homepage` | string | `""` | URL |
| `icon` | string | `""` | Phosphor icon class (`"ph ph-envelope"`) |
| `plugin_type` | string | `""` | Hint: `"platform"`, `"connector"`, `"monitor"`, `"tool"` |

### Feature Toggles

```json
"features": {
  "read_mail": {
    "description": "Read emails from inbox",
    "default": true
  },
  "send_mail": {
    "description": "Send emails",
    "default": false,
    "requires": ["read_mail"]
  }
}
```

Features can be toggled at runtime via `plugin.config.is_feature_enabled("read_mail")` (Python) or via the admin API.

### Interval Jobs

```json
"jobs": [
  {
    "id": "poll-inbox",
    "method": "poll_inbox",
    "interval_seconds": 60,
    "run_on_activate": true,
    "enabled_feature": "read_mail"
  }
]
```

Jobs run in executor threads — **never block the event loop**. Jobs gated by `enabled_feature` only run when that feature is on.

### Intent Handlers

```json
"intents": [
  {
    "scheme": "photo",
    "mime_types": ["image/jpeg", "image/png"],
    "method": "handle_photo",
    "description": "Process uploaded photo"
  }
]
```

### Flags

| Field | Type | Default | Description |
|---|---|---|---|
| `mcp` | bool | `false` | Plugin provides MCP tools |
| `soul` | string | `""` | Path to `SOUL.md` (agent instructions with feature-gated sections) |
| `documents` | bool | `false` | Plugin provides searchable documents |

### UI Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `ui_script` | string | `""` | Path to JS file relative to extension dir |
| `ui_widgets` | string[] | `[]` | Vue component names provided |

### Dependencies

| Field | Type | Default | Description |
|---|---|---|---|
| `depends_on` | string[] | `[]` | Plugin IDs that must be loaded first |
| `python_dependencies` | string[] | `[]` | PyPI packages required |

---

## Storage

### In-Memory vs Disk: When to Use What

| Data type | Storage | Example |
|---|---|---|
| Live metrics (CPU, network, processes) | **In-memory** (`self._latest`, `self._history`) | System monitor, network monitor |
| Persistent records (clipboard entries, config) | **Disk** (`self.store`, `self.files`) | Clipboard history, user settings |
| Thumbnail data | **In-memory** (cached on instance) | All plugins with `renderThumbnail` |

**Rule: Never write volatile/live data to disk.** Metrics that refresh every 5 seconds should live in instance variables (`self._latest`). Disk storage is only for data that must survive restarts.

**Pattern for live data plugins:**

```python
class MyMonitor(PluginBase, ScheduledMixin):
    def activate(self, config):
        self._latest = {}      # in-memory, volatile
        self._history = []     # in-memory, volatile

    def get_status(self):
        """Returns in-memory data for thumbnails and API."""
        return {"latest": self._latest, "history": self._history[-60:]}

    def poll_data(self):
        metrics = collect_metrics()
        self._latest = metrics
        self._history.append(metrics)
        if len(self._history) > 60:
            self._history = self._history[-60:]
        # NO self.store.put() — never write live metrics to disk
```

The `/api/plugins/{id}/status` endpoint calls `get_status()` and returns the in-memory data. The thumbnail renderer on the client fetches this every 5 seconds.

### Key-Value Store (`PluginStore`)

Every plugin gets an isolated key-value store via `self.store`. Values are dicts with optional TTL.

```python
class MyPlugin(PluginBase):
    async def save_reading(self, temp: float) -> None:
        await self.store.put(
            f"reading:{int(time.time())}",
            {"temperature": temp, "unit": "celsius"},
            ttl_seconds=86400,  # auto-delete after 24h
        )

    async def get_recent(self) -> list[dict]:
        return await self.store.query(
            filter_fn=lambda d: d.get("temperature", 0) > 50,
            limit=10,
        )
```

**API:**

| Method | Signature | Description |
|---|---|---|
| `get` | `async (key) → dict \| None` | Get by key, None if missing/expired |
| `put` | `async (key, value, ttl_seconds?)` | Create/replace, optional TTL |
| `delete` | `async (key) → bool` | Delete, returns True if existed |
| `list_keys` | `async (prefix?) → list[str]` | List non-expired keys |
| `query` | `async (filter_fn?, limit?) → list[dict]` | Filter documents |
| `cleanup_expired` | `async () → int` | Remove expired, returns count |

**Backends:**

| Backend | Class | Storage | TTL |
|---|---|---|---|
| File (default) | `FilePluginStore` | `~/.hort/plugins/{id}/data.json` | `_expires` field |
| MongoDB | `MongoPluginStore` | `plugin_{id}` collection | TTL index |

Auto-cleaning: the registry runs `cleanup_expired()` on all stores every 60 seconds.

### File Store (`PluginFileStore`)

Binary file storage with optional expiration. For photos, documents, cached data.

```python
class MyPlugin(PluginBase):
    async def save_photo(self, data: bytes) -> str:
        uri = await self.files.save(
            "photo_001.jpg", data,
            mime_type="image/jpeg",
            ttl_seconds=3600,  # auto-delete after 1h
        )
        return uri

    async def get_photo(self, name: str) -> bytes | None:
        result = await self.files.load(name)
        if result:
            data, mime = result
            return data
        return None
```

**API:**

| Method | Signature | Description |
|---|---|---|
| `save` | `async (name, data, mime?, ttl?) → str` | Save file, returns URI |
| `load` | `async (name) → (bytes, mime) \| None` | Load file |
| `delete` | `async (name) → bool` | Delete file |
| `list_files` | `async (prefix?) → list[FileInfo]` | List non-expired files |
| `cleanup_expired` | `async () → int` | Remove expired files |

**Backends:**

| Backend | Class | Storage |
|---|---|---|
| Local (default) | `LocalFileStore` | `~/.hort/plugins/{id}/files/` |
| Blob (future) | `BlobFileStore` | Azure Blob / S3 (via plugin) |

**Note:** MongoDB is NOT used for file storage. File storage is always local or blob-based.

### Shared Access

By default, a plugin can only access its own store. Cross-plugin access is opt-in via config:

```yaml
# hort-config.yaml
plugin.ai-assistant:
  shared_access: ["plugin.email-monitor", "plugin.calendar"]
```

The AI assistant plugin can then read (not write) the email monitor's store via `self.shared_stores["plugin.email-monitor"]`.

---

## Scheduler

Plugins run background jobs on intervals. Jobs execute in thread pool executors — **never blocking the event loop**.

**Startup behavior:** Plugin schedulers start 3 seconds after the server finishes startup. Jobs with `run_on_activate: true` in the manifest do NOT run immediately during server startup — the first interval cycle handles it. This prevents blocking the event loop during startup (e.g., `psutil.cpu_percent(interval=0.5)` for 5 plugins would block for 2.5s).

**Important:** `activate()` is always called on every plugin, even without explicit config (receives `{}`). Plugins MUST initialize their instance variables in `activate()`, not at class level — otherwise they won't exist when `get_status()` or scheduler jobs run.

### Declarative (in manifest)

```json
"jobs": [
  {"id": "poll-temp", "method": "poll_temperature", "interval_seconds": 10, "run_on_activate": true}
]
```

### Programmatic (in code)

```python
from hort.ext.scheduler import ScheduledMixin, JobSpec

class MyPlugin(PluginBase, ScheduledMixin):
    def get_jobs(self) -> list[JobSpec]:
        return [
            JobSpec(id="check", fn_name="check_status", interval_seconds=30),
        ]

    def check_status(self) -> None:
        # Runs every 30s in an executor thread
        ...
```

Both sources are merged — manifest jobs + `get_jobs()` result.

### Feature-Gated Jobs

```json
{"id": "send-alerts", "method": "send_alerts", "interval_seconds": 300, "enabled_feature": "alerts"}
```

If the `alerts` feature is disabled, the job won't start. Toggling the feature at runtime starts/stops the job.

---

## Intent System

Intents are Android-like URI handlers. A phone can send a photo, GPS coordinate, or file to any plugin that accepts it.

### Built-in URI Schemes

| Scheme | Payload | Example plugins |
|---|---|---|
| `photo` | JPEG/PNG bytes + metadata | Face detector, part inspector, photo album |
| `geo` | `{lat, lon, altitude?, accuracy?}` | Location tracker, weather, geofence |
| `file` | Binary + filename + mime | Document processor, backup, converter |
| `text` | Plain text string | Note taker, translator, search |
| `url` | URL string | Bookmark manager, web scraper |
| `contact` | vCard data | CRM, address book |
| `scan` | Barcode/QR content | Inventory, authentication |

### Handling Intents

**In manifest:**
```json
"intents": [
  {"scheme": "photo", "mime_types": ["image/jpeg", "image/png"], "method": "handle_photo", "description": "Analyze photo"}
]
```

**In code:**
```python
from hort.ext.intents import IntentMixin, IntentHandler

class MyPlugin(PluginBase, IntentMixin):
    def get_intent_handlers(self) -> list[IntentHandler]:
        return [
            IntentHandler(
                uri_scheme="photo",
                mime_types=["image/jpeg", "image/png"],
                description="Detect funny faces",
                method="handle_photo",
            ),
        ]

    async def handle_photo(self, data: bytes, metadata: dict) -> dict:
        # Process the photo
        faces = self.detect_faces(data)
        await self.files.save(f"result_{metadata['timestamp']}.jpg", result_data)
        return {"faces_found": len(faces)}
```

### API

```
GET  /api/intents                    → list all registered handlers
POST /api/intents/{scheme}           → route intent to matching plugin(s)
POST /api/intents/{scheme}/{plugin}  → route to specific plugin
```

When multiple plugins handle the same intent, the UI shows a picker dialog.

---

## MCP Integration

Plugins can provide tools for AI assistants via the Model Context Protocol.

```python
from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult

class MyPlugin(PluginBase, MCPMixin):
    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="get_temperature",
                description="Get current CPU temperature",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    async def execute_mcp_tool(self, tool_name: str, arguments: dict) -> MCPToolResult:
        if tool_name == "get_temperature":
            temp = self.read_temperature()
            return MCPToolResult(content=[{"type": "text", "text": f"{temp}°C"}])
        return MCPToolResult(content=[{"type": "text", "text": "Unknown tool"}], is_error=True)
```

Set `"mcp": true` in the manifest. Tools are aggregated by the MCP bridge (`hort/mcp/`) and served to Claude Code via stdio or SSE.

---

## SOUL.md — Agent Instructions

Each extension can provide a `SOUL.md` file that teaches the chat agent when and how to use its tools. The file is plain Markdown — readable on GitHub, editable by users, no special syntax beyond `Feature:` and `Tool:` metadata lines.

### Structure

```markdown
# My Extension

Preamble text — always included in the prompt.


## Read Emails

Feature: read_mail
Tool: get_inbox
Tool: search_email

When the user asks about their inbox, use get_inbox to fetch
recent messages. Use search_email for specific queries.

Always summarize — don't dump raw email content.


## Send Emails

Feature: send_mail
Tool: send_email
Tool: reply_email

Only send when the user explicitly asks. Always confirm
the recipient and subject before sending.
```

### How it works

- **Chapters** are split on `## ` headings
- **`Feature:` line** links the chapter to a feature toggle from the manifest
- **`Tool:` lines** (one per line) link MCP tools to the chapter
- **Everything else** is the instruction text injected into the system prompt

### Feature gating

When a feature is disabled (via config or admin API), two things happen simultaneously:

1. The chapter is **removed from the system prompt** — the agent doesn't know it exists
2. The linked tools are added to **`--disallowedTools`** — the agent can't call them

A single toggle controls both. Disabling `send_mail` removes the "Send Emails" chapter AND blocks `send_email` / `reply_email`.

### Manifest

Add `"soul": "SOUL.md"` to `extension.json`:

```json
{
  "name": "my-plugin",
  "mcp": true,
  "soul": "SOUL.md",
  "features": {
    "read_mail": { "description": "Read emails", "default": true },
    "send_mail": { "description": "Send emails", "default": false }
  }
}
```

### File layout

```
llmings/core/my_plugin/
  extension.json
  provider.py
  SOUL.md          ← agent instructions
  __init__.py
```

The `SOUL.md` is loaded by the MCP bridge server at startup and injected into the chat backend's system prompt. The preamble (text before the first `## `) is always included.

---

## Document Provision

Plugins provide searchable documents for AI to discover and read.

```python
from hort.ext.documents import DocumentMixin, DocumentDef

class MyPlugin(PluginBase, DocumentMixin):
    def get_documents(self) -> list[DocumentDef]:
        return [
            DocumentDef(
                uri="plugin://email-monitor/inbox-summary",
                name="Inbox Summary",
                description="Current email inbox status and recent messages",
                content_fn="get_inbox_summary",
            ),
        ]

    def get_inbox_summary(self) -> str:
        return f"You have {self.unread_count} unread emails..."
```

Documents are accessible via:
- MCP resources (`resources/list`, `resources/read`)
- HTTP: `GET /api/plugins/{plugin_id}/documents/{uri}`

---

## FastAPI Routers

Plugins can provide custom HTTP endpoints via detachable FastAPI routers.

```python
from fastapi import APIRouter

class MyPlugin(PluginBase):
    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/status")
        async def status():
            return {"temperature": 42, "unit": "celsius"}

        @router.post("/calibrate")
        async def calibrate(offset: float = 0.0):
            self.calibration_offset = offset
            return {"ok": True}

        return router
```

Routes are mounted at `/api/plugins/{plugin_id}/...`:
- `GET /api/plugins/my-plugin/status`
- `POST /api/plugins/my-plugin/calibrate`

Routers are **detachable** — when a plugin is unloaded, its routes are removed from the app.

**Sandboxing:** Plugin routes live under `/api/plugins/{id}/` — they cannot shadow core routes or other plugins' routes.

---

## UI Development

### Theme System

Plugins MUST use CSS custom properties — never hardcode colors.

```css
/* Available variables (dark mode) */
--el-bg: #0a0e1a;
--el-surface: #111827;
--el-surface-elevated: #1a2436;
--el-border: #1e3a5f;
--el-primary: #3b82f6;
--el-accent: #6366f1;
--el-text: #f0f4ff;
--el-text-dim: #94a3b8;
--el-danger: #ef4444;
--el-success: #22c55e;
--el-warning: #f59e0b;
--el-widget-radius: 10px;
--el-widget-padding: 16px;
```

**Rule:** These variables switch automatically in light mode (`.theme-light` on root). Plugins that use them will work in both modes without changes.

### Icons

Two icon sets are available:

**Phosphor Icons** (primary, for plugin UI):
```html
<i class="ph ph-thermometer"></i>          <!-- regular -->
<i class="ph-bold ph-thermometer"></i>     <!-- bold -->
<i class="ph-fill ph-thermometer"></i>     <!-- fill -->
```
Browse: https://phosphoricons.com/

**Material Icons** (system UI):
```html
<i class="material-icons">settings</i>
```
Browse: https://fonts.google.com/icons

### Shared Widget Components

Registered globally by `hort-widgets.js`. Available in any plugin template:

#### `<hort-stat-card>`
Single number with label, trend indicator, and icon.

```html
<hort-stat-card
  label="CPU Temperature"
  value="42"
  unit="°C"
  trend="up"
  icon="ph ph-thermometer"
  color="var(--el-warning)"
/>
```

| Prop | Type | Description |
|---|---|---|
| `label` | String | Card title |
| `value` | String | Main number/text |
| `unit` | String | Unit suffix |
| `trend` | String | `"up"` / `"down"` / `"flat"` / `""` |
| `icon` | String | Icon class |
| `color` | String | Accent color (CSS variable recommended) |

#### `<hort-chart>`
Plotly.js wrapper with reactive data.

```html
<hort-chart
  type="line"
  :data="[{x: timestamps, y: values, name: 'Temperature'}]"
  :layout="{title: 'CPU Temperature', height: 200}"
/>
```

| Prop | Type | Description |
|---|---|---|
| `type` | String | `"line"` / `"bar"` / `"gauge"` / `"pie"` |
| `data` | Array | Plotly trace objects |
| `layout` | Object | Plotly layout options |

#### `<hort-status-badge>`
Colored status indicator.

```html
<hort-status-badge status="ok" label="Service running" />
```

| Prop | Type | Description |
|---|---|---|
| `status` | String | `"ok"` / `"warn"` / `"error"` / `"offline"` |
| `label` | String | Description text |

#### `<hort-data-table>`
Responsive data table.

```html
<hort-data-table
  :columns="[{name: 'name', label: 'Name'}, {name: 'value', label: 'Value'}]"
  :rows="[{name: 'CPU', value: '42°C'}, {name: 'RAM', value: '67%'}]"
  dense
/>
```

#### `<hort-widget-grid>`
Responsive grid layout for multiple widgets.

```html
<hort-widget-grid :widgets="[
  {component: 'my-stat-card', props: {...}, sizes: {phone: 12, tablet: 6, pc: 4}},
  {component: 'my-chart', props: {...}, sizes: {phone: 12, tablet: 12, pc: 8}},
]" />
```

Uses a 12-column grid system:
- **Phone** (< 480px): typically `cols: 12` (full width)
- **Tablet** (480–1023px): typically `cols: 6` (half)
- **PC** (1024px+): typically `cols: 4` (third)

#### `<hort-qr>`
QR code with clickable URL (already exists).

```html
<hort-qr :url="myUrl" label="Scan to connect" />
```

#### `<hort-intent-picker>`
Shows available intent handlers when multiple plugins accept the same intent.

#### `<hort-file-upload>`
File upload button that sends to the plugin's file store.

### Plugin Isolation (Browser)

- Wrap your root template in `<div data-plugin="your-plugin-id">`
- Use `this.localStorage(key)` and `this.localStorage(key, value)` for namespaced storage
- API calls via `this.api(path)` / `this.apiPost(path, body)` are auto-prefixed to `/api/plugins/{id}/`
- CSS scope with `[data-plugin="my-plugin"] .my-class { ... }`

### Widget Modes: Compact + Thumbnail (mandatory), Desktop (optional)

Every plugin MUST provide at minimum:

1. **Thumbnail** (`renderThumbnail(ctx, 320, 200)`) — canvas-based preview for the grid card. Shows essential info at a glance (numbers, bars, status). Updated every 5s. The thumbnail is drawn on an offscreen canvas and displayed as a JPEG data URL in the card's `<img>` tag. Cache data in instance properties (e.g. `this._lastMetrics`) from the component's refresh cycle, then draw from cache in `renderThumbnail`.

   **Data flow for thumbnails:**

   ```
   Server (Python)                    Client (JavaScript)
   ┌─────────────────┐               ┌──────────────────────────┐
   │ poll_metrics()   │  every 5s     │ fetch /api/plugins/      │
   │ → self._latest   │ ───────────→ │   {name}/status          │
   │ → self._history  │  (in-memory) │ → inst._feedStore(data)  │
   │                  │               │ → renderThumbnail(ctx)   │
   │ get_status()     │               │ → canvas → data URL      │
   │ → {latest,       │               │ → <img> in grid card     │
   │    history}      │               └──────────────────────────┘
   └─────────────────┘
   ```

   **Python side:** `get_status()` returns in-memory data (no disk I/O).
   **JS side:** `_feedStore(status)` caches data on the extension instance. `renderThumbnail()` reads from cache and draws.

   **Implementation:**
   - Python: `self._latest = metrics` in `poll_*()`, `get_status()` returns it
   - JS: `_feedStore(store)` sets `this._lastMetrics = store.latest`
   - JS: `renderThumbnail(ctx, w, h)` draws from `this._lastMetrics`
   - Colors: use hex directly (not CSS vars — canvas doesn't support them). `#111827` bg, `#f0f4ff` text, `#94a3b8` dim, `#f59e0b` amber, `#3b82f6` blue, `#22c55e` green, `#ef4444` red.
   - Charts: donut pie (disk usage), sparklines (CPU/MEM), horizontal bars (processes), large numbers (network)

2. **Compact mode** — the default widget rendered inside the lightbox overlay (480px max). Must work on smartphone screens (both portrait and landscape). Use the `.widget-regions` CSS class for auto-wrapping layouts:

```html
<div class="widget-regions">
  <div class="widget-region"><!-- stat cards --></div>
  <div class="widget-region"><!-- chart or table --></div>
</div>
```

Regions wrap vertically on phones, sit side-by-side on tablets. Each region stretches to fill available width. This gives landscape mode 2-3 columns and portrait mode a single scrollable column.

3. **Desktop mode** (optional) — an expanded view with more detail, used when the plugin is pinned to the Llmings grid. Can use the full grid width. Only implement if the compact mode is insufficient for the data being shown.

**Responsive behavior:**

| Context | Width | Layout |
|---|---|---|
| Llming detail (phone portrait) | 100% screen | Single column, full height |
| Llming detail (phone landscape) | 100% screen | 2 regions side by side |
| Llming detail (tablet/desktop) | 480px centered | 2 regions side by side |
| Llmings grid (pinned panel) | Grid column width | Compact, adapt to card |

**Rules:**
- Never hardcode pixel widths — use `100%`, `flex`, and `min-width`
- Use `.widget-regions` for multi-section layouts
- Use `hort-stat-card` for key numbers (auto-wraps in grid)
- Use Plotly.js for charts with `responsive: true`
- Test in both portrait and landscape on a real phone or Chrome DevTools

### Responsive Design

All widgets must work on phone, tablet, and PC. Use:
- Quasar's responsive utilities (`$q.screen.lt.md` for mobile detection)
- The `<hort-widget-grid>` component for automatic responsive layout
- Flexbox with `flex-wrap: wrap` for custom layouts
- `font-size: clamp(12px, 2vw, 16px)` for fluid typography

---

## Configuration

Each plugin has its own config namespace in `hort-config.yaml`:

```yaml
plugin.my-plugin:
  threshold: 85
  email: admin@example.com
  _feature_overrides:
    alerts: true
    logging: false
  shared_access: ["plugin.other-plugin"]
```

**Python access:**
```python
class MyPlugin(PluginBase):
    def activate(self, config: dict) -> None:
        threshold = self.config.get("threshold", 80)
        if self.config.is_feature_enabled("alerts"):
            self.start_alerting(threshold)
```

**JavaScript access:**
```javascript
// Fetch config via API
const cfg = await fetch(HortExtension.basePath + '/api/config/plugin.my-plugin').then(r => r.json());
```

---

## Security & Sandboxing

### Server-Side Isolation

| Resource | Namespace | Implementation |
|---|---|---|
| HTTP routes | `/api/plugins/{id}/...` | FastAPI sub-app mount |
| Config | `plugin.{id}` | ConfigStore keyed access |
| Data store | `~/.hort/plugins/{id}/data.json` | Separate `FilePluginStore` |
| File store | `~/.hort/plugins/{id}/files/` | Separate `LocalFileStore` |
| Scheduler | Per-plugin `PluginScheduler` | Cannot access other schedulers |
| Logger | `hort.plugin.{id}` | Standard Python logging |
| MCP tools | Prefixed by plugin ID | Aggregated, non-conflicting |

### Client-Side Isolation

| Resource | Namespace | Implementation |
|---|---|---|
| localStorage | `hort.plugin.{id}.{key}` | `HortExtension.localStorage()` |
| API calls | `/api/plugins/{id}/...` | Auto-prefixed by `HortExtension.api()` |
| CSS | `[data-plugin="id"]` scope | Convention-based |
| DOM | `<div data-plugin="id">` wrapper | Convention-based |

### Cross-Plugin Access

By default: **none**. A plugin cannot read another plugin's store, files, or config.

Opt-in via `shared_access` config: grants read-only access to specified plugin stores via `self.shared_stores`.

---

## Testing

### Plugin Test Harness

Test any plugin in isolation — no server, no DB, no other plugins:

```python
from tests.plugin_harness import PluginTestHarness

class TestMyPlugin:
    @pytest.fixture
    def harness(self, tmp_path):
        return PluginTestHarness(MyPlugin, config={"threshold": 85}, tmp_path=tmp_path)

    async def test_poll_stores_reading(self, harness):
        await harness.activate()
        harness.instance.poll_temperature()
        keys = await harness.store.list_keys("reading:")
        assert len(keys) == 1

    async def test_feature_toggle(self, harness):
        await harness.activate()
        assert harness.instance.config.is_feature_enabled("alerts") is True
        harness.instance.config.set_feature("alerts", False)
        assert harness.instance.config.is_feature_enabled("alerts") is False
```

### Store Backend Equivalence

Both FilePluginStore and MongoPluginStore pass the same parameterized test suite:

```python
@pytest.fixture(params=["file", "mongo"])
async def plugin_store(request, tmp_path):
    if request.param == "file":
        return FilePluginStore("test", base_dir=tmp_path)
    elif request.param == "mongo":
        pytest.importorskip("mongomock")
        import mongomock
        return MongoPluginStore("test", mongomock.MongoClient()["test_db"])
```

### Widget Rendering

Use Playwright for visual verification:

```python
@pytest.mark.integration
def test_stat_card_renders(page):
    page.goto("http://localhost:8940/viewer")
    card = page.locator("[data-plugin='my-plugin'] .hort-stat-card")
    assert card.is_visible()
```

---

## Admin API

```
GET  /api/admin/plugins                           → list all plugins with status
POST /api/admin/plugins/reload                     → re-scan and load new plugins
POST /api/admin/plugins/{id}/unload                → hot-unload a plugin
GET  /api/admin/plugins/{id}/features              → list feature toggles
POST /api/admin/plugins/{id}/features/{feature}    → toggle feature {enabled: bool}
GET  /api/intents                                  → list registered intent handlers
POST /api/intents/{scheme}                         → route intent to handler(s)
GET  /api/plugins/{id}/documents/{uri}             → read plugin document
GET  /mcp                                          → MCP endpoint (aggregated tools + resources)
GET  /api/qr?url=...                               → generate QR code for any URL
```

---

## Python Classes Reference

### Base Classes (`hort/ext/plugin.py`)

| Class | Purpose |
|---|---|
| `PluginBase` | Enhanced `ExtensionBase` with injected context |
| `PluginContext` | Holds store, files, config, scheduler, logger |
| `PluginConfig` | Config access with feature toggle support |

### Mixins

| Mixin | File | Purpose |
|---|---|---|
| `ScheduledMixin` | `hort/ext/scheduler.py` | `get_jobs() → list[JobSpec]` |
| `MCPMixin` | `hort/ext/mcp.py` | `get_mcp_tools()`, `execute_mcp_tool()` |
| `DocumentMixin` | `hort/ext/documents.py` | `get_documents() → list[DocumentDef]` |
| `IntentMixin` | `hort/ext/intents.py` | `get_intent_handlers() → list[IntentHandler]` |

### Storage (`hort/ext/store.py`, `hort/ext/file_store.py`)

| Class | Purpose |
|---|---|
| `PluginStore` | ABC for key-value store with TTL |
| `FilePluginStore` | JSON file backend |
| `MongoPluginStore` | MongoDB backend |
| `PluginFileStore` | ABC for binary file store with TTL |
| `LocalFileStore` | Local filesystem backend |
| `FileInfo` | File metadata dataclass |

### Scheduler (`hort/ext/scheduler.py`)

| Class | Purpose |
|---|---|
| `PluginScheduler` | Manages asyncio interval tasks |
| `JobSpec` | Job definition dataclass |

### Manifest (`hort/ext/manifest.py`)

| Class | Purpose |
|---|---|
| `ExtensionManifest` | Parsed extension.json with all fields |
| `FeatureToggle` | Feature toggle definition |
| `JobManifest` | Declarative job definition |
| `IntentManifest` | Declarative intent handler |

---

## Example: System Monitor Plugin

A complete plugin that monitors CPU temperature, runs background polling, provides a dashboard widget, MCP tools, and documents.

**extension.json:**
```json
{
  "name": "system-monitor",
  "version": "0.1.0",
  "description": "Monitors system health — CPU temp, memory, disk",
  "provider": "core",
  "platforms": ["darwin", "linux"],
  "capabilities": ["monitor", "mcp"],
  "entry_point": "provider:SystemMonitor",
  "icon": "ph ph-cpu",
  "author": "openhort",
  "plugin_type": "monitor",
  "features": {
    "temperature": {"description": "Monitor CPU temperature", "default": true},
    "memory": {"description": "Monitor memory usage", "default": true},
    "alerts": {"description": "Alert on thresholds", "default": false}
  },
  "jobs": [
    {"id": "poll", "method": "poll_metrics", "interval_seconds": 10, "run_on_activate": true}
  ],
  "mcp": true,
  "documents": true,
  "ui_widgets": ["system-monitor-dashboard"],
  "ui_script": "static/panel.js"
}
```

**provider.py:**
```python
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin
from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.documents import DocumentMixin, DocumentDef

class SystemMonitor(PluginBase, ScheduledMixin, MCPMixin, DocumentMixin):
    def activate(self, config):
        self.threshold = self.config.get("threshold_celsius", 85)
        self.log.info("System monitor started (threshold=%d°C)", self.threshold)

    def poll_metrics(self):
        import psutil
        temp = psutil.sensors_temperatures().get("coretemp", [{}])[0].current
        mem = psutil.virtual_memory().percent
        self.store.put("latest", {"temp": temp, "mem": mem}, ttl_seconds=3600)

    def get_mcp_tools(self):
        return [MCPToolDef(name="get_system_health", description="Current CPU temp and memory", input_schema={"type": "object"})]

    async def execute_mcp_tool(self, name, args):
        data = await self.store.get("latest") or {}
        return MCPToolResult(content=[{"type": "text", "text": f"CPU: {data.get('temp', '?')}°C, Memory: {data.get('mem', '?')}%"}])

    def get_documents(self):
        return [DocumentDef(uri="plugin://system-monitor/health", name="System Health", content_fn="get_health_doc")]

    def get_health_doc(self):
        return "System health report..."
```

**static/panel.js:**
```javascript
class SystemMonitorPanel extends HortExtension {
    static id = 'system-monitor';
    static name = 'System Monitor';
    static llmingTitle = 'System Monitor';
    static llmingIcon = 'ph ph-cpu';
    static llmingDescription = 'CPU, memory, and disk monitoring';

    setup(app, Quasar) {
        app.component('system-monitor-dashboard', {
            setup() {
                const temp = Vue.ref('--');
                const mem = Vue.ref('--');
                // Poll latest metrics
                async function refresh() {
                    const data = await fetch(HortExtension.basePath + '/api/config/plugin.system-monitor').then(r => r.json());
                    // ... update refs
                }
                Vue.onMounted(() => { refresh(); setInterval(refresh, 10000); });
                return { temp, mem };
            },
            template: `
                <div data-plugin="system-monitor">
                    <hort-widget-grid :widgets="[
                        {component: 'hort-stat-card', props: {label: 'CPU', value: temp, unit: '°C', icon: 'ph ph-thermometer', color: 'var(--el-warning)'}},
                        {component: 'hort-stat-card', props: {label: 'Memory', value: mem, unit: '%', icon: 'ph ph-hard-drives', color: 'var(--el-primary)'}},
                    ]" />
                </div>
            `,
        });
    }
}
HortExtension.register(SystemMonitorPanel);
```

---

## Connector Framework

### Overview

The connector framework (`hort/ext/connectors.py`) provides a unified messaging interface for platforms like Telegram, Discord, and WhatsApp. Connectors receive messages, route commands to plugins, and send formatted responses.

Message flow:

```
User → Connector (Telegram/Discord/...) → CommandRegistry → Plugin → ConnectorResponse → Connector → User
```

### Architecture

- **`ConnectorBase`** — Abstract base for messaging connectors. Implements `start()`, `stop()`, `send_response()`, and `render_text()` (fallback chain: HTML → Markdown → plain text).
- **`ConnectorMixin`** — Mixin for plugins that provide commands. Implement `get_connector_commands()` and `handle_connector_command()`.
- **`CommandRegistry`** — Routes commands to plugins. System commands (defined by the connector) cannot be overridden by plugins.
- **`ConnectorResponse`** — Response with `text`, `markdown`, `html`, `image`, `buttons` fields. The connector picks the best format for its capabilities.
- **`IncomingMessage`** — Normalized message from any platform. Parses `/command args` syntax, strips `@botname` suffixes.
- **`ConnectorCapabilities`** — Declares what a connector can render (text, markdown, html, images, files, inline buttons, commands, location, max text length).
- **`ConnectorCommand`** — Command registration with name, description, plugin ID, usage, and flags (`hidden`, `accept_images`, `accept_files`, `system`).
- **`ResponseButton`** — Interactive button with label and callback data, used in `ConnectorResponse.buttons` (rows of buttons).

### System Commands

System commands are defined in the connector provider (e.g. `SYSTEM_COMMANDS` in `telegram_connector/provider.py`) and take priority over plugin commands. They have `system=True` set on the `ConnectorCommand`, which prevents plugins from overriding them.

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | List all commands (system + plugin) |
| `/link` | Temporary access link |
| `/status` | Server status (CPU, memory, uptime) |
| `/screenshot` | Capture screen |
| `/windows` | List open windows |
| `/targets` | List connected machines |
| `/spaces` | List virtual desktops |

### Adding Commands to a Plugin

Any plugin can expose commands to all connectors by mixing in `ConnectorMixin`:

```python
from hort.ext.connectors import ConnectorCapabilities, ConnectorCommand, ConnectorMixin, ConnectorResponse, IncomingMessage
from hort.ext.plugin import PluginBase

class MyPlugin(PluginBase, ConnectorMixin):
    def get_connector_commands(self) -> list[ConnectorCommand]:
        return [
            ConnectorCommand(name="mycommand", description="Does something", plugin_id="my-plugin"),
        ]

    async def handle_connector_command(
        self, command: str, message: IncomingMessage, capabilities: ConnectorCapabilities
    ) -> ConnectorResponse | None:
        if command == "mycommand":
            return ConnectorResponse.simple(f"Result: {message.command_args}")
        return None
```

- `get_connector_commands()` returns the list of commands this plugin provides.
- `handle_connector_command()` is called when a user sends one of those commands. Return `None` if not handled (a fallback message is sent automatically).
- The `capabilities` argument lets you adapt responses to the platform (e.g. send an image only if `capabilities.images` is True).

### ConnectorResponse Formats

`ConnectorResponse` supports multiple output formats. The connector picks the best one it supports:

```python
# Plain text
ConnectorResponse.simple("Hello, world!")

# Rich text with HTML and plain fallback
ConnectorResponse(
    text="Hello, world!",
    html="<b>Hello, world!</b>",
)

# Image with caption
ConnectorResponse.with_image(jpeg_bytes, caption="Screenshot of desktop")

# Interactive buttons (rows of buttons)
from hort.ext.connectors import ResponseButton
ConnectorResponse(
    text="Pick an option:",
    buttons=[
        [ResponseButton(label="Option A", callback_data="pick:a"),
         ResponseButton(label="Option B", callback_data="pick:b")],
    ],
)
```

Rendering priority: `html` → `markdown` → `text`. If HTML sending fails, `send_response()` automatically falls back to plain text.

### Creating a New Connector

1. Create an extension directory under `llmings/core/` (e.g. `discord_connector/`)
2. Inherit from both `PluginBase` and `ConnectorBase`
3. Implement the required abstract members:
   - `connector_id` (property) — unique ID string like `"discord"`
   - `capabilities` (property) — `ConnectorCapabilities` declaring what the platform supports
   - `start()` — start the connector (polling, webhook listener, etc.)
   - `stop()` — stop the connector gracefully (cancel tasks, close sessions)
   - `send_response(chat_id, response)` — send a `ConnectorResponse` to a specific chat, adapting to platform capabilities
4. Add a `set_command_registry(registry)` method to receive the `CommandRegistry`
5. Handle system commands in your message handler, delegate plugin commands to `self._registry.dispatch()`
6. Create `static/panel.js` for the UI panel (use `connector-panel` CSS classes)
7. Add the connector chip to `index.html` header alongside LAN and Cloud

**Minimal skeleton:**

```python
from hort.ext.connectors import (
    CommandRegistry, ConnectorBase, ConnectorCapabilities,
    ConnectorCommand, ConnectorResponse, IncomingMessage,
)
from hort.ext.plugin import PluginBase

SYSTEM_COMMANDS = [
    ConnectorCommand(name="start", description="Welcome message", system=True),
    ConnectorCommand(name="help", description="List all commands", system=True),
    # ... other system commands
]

class MyConnector(PluginBase, ConnectorBase):
    _registry: CommandRegistry | None = None

    @property
    def connector_id(self) -> str:
        return "my-platform"

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(text=True, images=True)

    async def start(self) -> None:
        # Start polling / webhook listener
        ...

    async def stop(self) -> None:
        # Cancel tasks, close connections
        ...

    async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
        text = self.render_text(response)  # uses fallback chain
        # Send text (and image if response.image) to the platform
        ...

    def set_command_registry(self, registry: CommandRegistry) -> None:
        self._registry = registry

    async def _handle(self, message: IncomingMessage) -> ConnectorResponse | None:
        if message.is_command:
            cmd = message.command
            # Handle system commands first
            if cmd == "start":
                return ConnectorResponse.simple("Welcome!")
            if cmd == "help":
                return self._build_help()
            # Delegate to plugin commands
            if self._registry:
                return await self._registry.dispatch(message, self.capabilities)
        return ConnectorResponse.simple("Send /help for available commands.")
```

### Lifecycle

Connectors are managed by the plugin lifecycle in `hort/plugins.py`:

1. **Discovery** — Connectors are discovered like any other extension during `setup_plugins()`.
2. **Loading** — The connector class is instantiated and `activate(config)` is called.
3. **Startup** — `start_plugins()` calls `_start_connectors()`, which:
   - Creates a `CommandRegistry`
   - Registers system commands (from the connector provider's `SYSTEM_COMMANDS`)
   - Collects commands from all plugins that implement `ConnectorMixin` (but are not themselves connectors)
   - Calls `set_command_registry(registry)` on each connector
   - Calls `start()` on each connector
4. **Runtime** — The connector polls/receives messages and routes them through the registry.
5. **Shutdown** — `stop_plugins()` calls `stop()` on each connector, then stops all schedulers.

**Important for `uvicorn --reload`:** The Telegram connector calls `delete_webhook(drop_pending_updates=True)` before starting to poll, ensuring only one instance polls at a time. Without this, the old and new worker would conflict. Other connectors should implement similar deduplication.

### Formatting Guidelines

- Use **HTML** (`<b>bold</b>`) not Markdown v1 (`*bold*`) for Telegram responses — Markdown v1 breaks on em-dashes, slashes, and other common punctuation.
- Always provide a plain `text` fallback alongside `html` or `markdown`.
- `send_response()` should catch formatting errors and automatically fall back to plain text (the Telegram connector does this).
- Long messages should be chunked to respect `capabilities.max_text_length` (4096 for Telegram).

### UI Panel

Each connector has a `static/panel.js` that extends `HortExtension` and registers a Vue component using the `connector-panel` CSS classes. The panel shows connection status, configuration, and setup hints. The connector chip appears in the `index.html` header alongside the LAN and Cloud chips when the connector extension is discovered.

### IncomingMessage Properties

`IncomingMessage` provides convenience properties for parsing commands:

| Property | Type | Description |
|---|---|---|
| `is_command` | `bool` | True if text starts with `/` |
| `command` | `str` | Command name without `/` or `@bot` suffix (e.g. `"help"`) |
| `command_args` | `str` | Everything after the command (e.g. `"search term"` from `/find search term`) |
| `callback_data` | `str \| None` | Data from inline button press |

### CommandRegistry Dispatch

When `CommandRegistry.dispatch()` is called:

1. If the message is not a command, returns `None`.
2. Looks up the command name in the registry.
3. If the command is a system command (`system=True`), returns `None` — the connector handles it directly.
4. If it is a plugin command, calls `handle_connector_command()` on the owning plugin.
5. If the plugin returns `None`, a default "no response" message is sent.
6. If the command is not found, an "Unknown command" message with a `/help` hint is returned.
