# Polyglot Plugin System — Python + Node.js on a Single Server

## Problem

Hort's plugin ecosystem is Python-only. The npm ecosystem has a massive library surface (UI components, real-time tools, messaging SDKs like Baileys, protocol implementations) that's inaccessible. We need Node.js plugins to run alongside Python plugins on the same server, sharing the same store, config, scheduler, and connector APIs.

## Prior Art & What We Learned

| System | Model | Takeaway |
|---|---|---|
| **VS Code** | Shared Node.js host process | Single-language only. No isolation between extensions. |
| **Grafana** | gRPC over Unix sockets (go-plugin) | Gold standard for polyglot. Per-plugin process isolation. Auto-restart on crash. |
| **Home Assistant** | Python in-process + Docker containers for others | Two-tier model is pragmatic. Docker for isolation, in-process for tight integration. |
| **MCP** | JSON-RPC 2.0 over stdio | Simplest viable protocol. Language-agnostic. Capability negotiation. Battle-tested. |
| **LSP** | JSON-RPC over stdio with Content-Length framing | Proven at scale (100+ implementations). Framing prevents message corruption. |
| **HashiCorp go-plugin** | gRPC with handshake-on-stdout | Elegant bootstrap. Plugin prints connection info on startup. Reattach across host restarts. |
| **n8n** | Subprocess-per-execution for Python | Too expensive. No persistent state. Don't do this. |

**Decision:** JSON-RPC 2.0 over stdio, with MCP-style capability negotiation and Grafana-style process supervision. No gRPC — it adds a build step and binary dependency that would hurt the npm plugin DX. JSON is debuggable, and the serialization cost is negligible for our message sizes.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     hort server (Python)                 │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Python Plugin │  │ Python Plugin │  │ Plugin Host    │  │
│  │ (in-process)  │  │ (in-process)  │  │ Manager        │  │
│  └──────────────┘  └──────────────┘  │                 │  │
│                                       │ Supervises      │  │
│                                       │ out-of-process  │  │
│                                       │ plugins         │  │
│                                       └──┬──────┬──────┘  │
│                                          │      │         │
│                    ┌─────────────────────┘      └──────┐  │
│                    │ stdio (JSON-RPC)                   │  │
│              ┌─────┴──────┐                ┌───────────┴┐ │
│              │ node host   │                │ node host   │ │
│              │ (1 process  │                │ (1 process  │ │
│              │  per plugin)│                │  per plugin)│ │
│              │             │                │             │ │
│              │ npm-plugin-a│                │ npm-plugin-b│ │
│              └─────────────┘                └─────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Why One Process Per Plugin (Not a Shared Node Host)

- **Crash isolation** — one plugin can't take down others
- **Independent dependencies** — each plugin has its own node_modules
- **Resource limits** — can set memory/CPU limits per process
- **Simple lifecycle** — start/stop/restart individual plugins without affecting others
- **Same model as Python** — Python plugins are isolated by being separate class instances; Node plugins are isolated by being separate processes

### Why Not Docker?

Docker is overkill for trusted first-party plugins. It adds startup latency (~1-3s), requires Docker Desktop on macOS, and complicates development. Reserve Docker for untrusted third-party plugins in a future "sandboxed marketplace" tier.

## Wire Protocol

### Transport

JSON-RPC 2.0 over stdio with **Content-Length framing** (LSP-style, not newline-delimited). This prevents corruption from plugins that accidentally write to stdout.

```
Content-Length: 73\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"activate","params":{"config":{}}}
```

**Rules:**
- Host writes to plugin's stdin, reads from plugin's stdout
- Plugin MUST NOT write anything to stdout except framed JSON-RPC messages
- Plugin logs go to stderr (captured by host, forwarded to hort's logger)
- Binary data (images, files) is base64-encoded within JSON

### Bootstrap Sequence

```
Host                                    Plugin (Node.js process)
  │                                          │
  │──── spawn process ──────────────────────>│
  │                                          │
  │<──── ready line on stderr ──────────────│  (stderr: "HORT_PLUGIN_READY\n")
  │                                          │
  │──── initialize ─────────────────────────>│
  │      {protocolVersion, pluginId,         │
  │       capabilities: [...]}               │
  │                                          │
  │<──── initialize response ───────────────│
  │      {capabilities: [...],               │
  │       commands: [...],                   │
  │       jobs: [...],                       │
  │       intents: [...],                    │
  │       mcpTools: [...],                   │
  │       documents: [...]}                  │
  │                                          │
  │──── activate ───────────────────────────>│
  │      {config: {...}}                     │
  │                                          │
  │<──── activate response ─────────────────│
  │      {ok: true}                          │
  │                                          │
  │          ┌─── normal operation ───┐      │
  │          │  requests/responses    │      │
  │          │  notifications         │      │
  │          └────────────────────────┘      │
  │                                          │
  │──── deactivate ─────────────────────────>│
  │                                          │
  │<──── deactivate response ───────────────│
  │                                          │
  │          (host closes stdin, process exits)
```

### Capability Negotiation

The host declares what APIs it offers. The plugin declares what it uses. This allows protocol evolution without breaking old plugins.

```jsonc
// Host → Plugin (initialize)
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2026-03-23",
    "pluginId": "my-npm-plugin",
    "hostCapabilities": [
      "store",           // key-value store API
      "files",           // binary file store API
      "config",          // config read/write
      "scheduler",       // interval job scheduling
      "log",             // structured logging
      "connector",       // messaging connector commands
      "mcp",             // MCP tool registration
      "documents",       // document provision
      "intents",         // intent handling
      "http"             // HTTP route registration
    ]
  }
}

// Plugin → Host (initialize response)
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2026-03-23",
    "pluginCapabilities": ["store", "config", "connector", "scheduler"],
    "commands": [
      {"name": "status", "description": "Show status"}
    ],
    "jobs": [
      {"id": "poll", "interval_seconds": 10, "run_on_activate": true}
    ],
    "intents": [],
    "mcpTools": [],
    "documents": []
  }
}
```

### Message Categories

#### 1. Lifecycle (Host → Plugin)

```jsonc
// activate
{"method": "activate", "params": {"config": {"key": "value"}}}
// → {"result": {"ok": true}}

// deactivate
{"method": "deactivate", "params": {}}
// → {"result": {"ok": true}}

// health (periodic, must respond within 5s)
{"method": "health", "params": {}}
// → {"result": {"ok": true, "memory_mb": 42}}
```

#### 2. Store Operations (Plugin → Host)

The plugin calls the host to read/write its store. The host proxies to the same `FilePluginStore` that Python plugins use.

```jsonc
// store.get
{"method": "store.get", "params": {"key": "latest"}}
// → {"result": {"cpu": 45, "mem": 62}}   or   {"result": null}

// store.put
{"method": "store.put", "params": {"key": "latest", "value": {"cpu": 45}, "ttl_seconds": 300}}
// → {"result": {"ok": true}}

// store.delete
{"method": "store.delete", "params": {"key": "old-entry"}}
// → {"result": {"deleted": true}}

// store.list_keys
{"method": "store.list_keys", "params": {"prefix": "history:"}}
// → {"result": ["history:1711200000", "history:1711200060"]}

// store.query
{"method": "store.query", "params": {"limit": 10}}
// → {"result": [{"cpu": 45}, {"cpu": 50}]}
```

#### 3. File Operations (Plugin → Host)

```jsonc
// files.save (binary data is base64-encoded)
{"method": "files.save", "params": {
  "name": "screenshot.jpg",
  "data_b64": "/9j/4AAQ...",
  "mime_type": "image/jpeg",
  "ttl_seconds": 86400
}}
// → {"result": {"uri": "file://screenshot.jpg"}}

// files.load
{"method": "files.load", "params": {"name": "screenshot.jpg"}}
// → {"result": {"data_b64": "/9j/4AAQ...", "mime_type": "image/jpeg"}}
// → {"result": null}  (if not found)

// files.delete
{"method": "files.delete", "params": {"name": "screenshot.jpg"}}
// → {"result": {"deleted": true}}

// files.list
{"method": "files.list", "params": {"prefix": ""}}
// → {"result": [{"name": "screenshot.jpg", "mime_type": "image/jpeg", "size": 54321, "created_at": 1711200000, "expires_at": 1711286400}]}
```

#### 4. Config Operations (Plugin → Host)

```jsonc
// config.get
{"method": "config.get", "params": {"key": "threshold"}}
// → {"result": 85}

// config.get_all
{"method": "config.get_all", "params": {}}
// → {"result": {"threshold": 85, "enabled": true}}

// config.set
{"method": "config.set", "params": {"key": "threshold", "value": 90}}
// → {"result": {"ok": true}}

// config.is_feature_enabled
{"method": "config.is_feature_enabled", "params": {"feature": "alerts"}}
// → {"result": true}

// config.set_feature
{"method": "config.set_feature", "params": {"feature": "alerts", "enabled": false}}
// → {"result": {"ok": true}}
```

#### 5. Logging (Plugin → Host, notification — no response)

```jsonc
{"method": "log", "params": {"level": "info", "message": "Polling started", "data": {"interval": 10}}}
{"method": "log", "params": {"level": "error", "message": "Connection failed", "data": {"url": "http://..."}}}
```

No response — these are JSON-RPC notifications (no `id` field).

#### 6. Scheduler (Host → Plugin)

The host manages the timer. When a job fires, the host calls the plugin.

```jsonc
// Host → Plugin: run a scheduled job
{"method": "job.run", "params": {"job_id": "poll"}}
// → {"result": {"ok": true}}
// (Plugin does its work, uses store.put etc. to save results)
```

This is simpler than having the plugin manage its own timers. The host already has a scheduler — it just calls the plugin when it's time.

#### 7. Connector Commands (Host → Plugin)

When a user sends `/status` in Telegram and the plugin registered that command:

```jsonc
// Host → Plugin: handle command
{
  "method": "connector.command",
  "params": {
    "command": "status",
    "args": "",
    "connector_id": "telegram",
    "user": {"id": "12345", "username": "alice_dev"},
    "chat_id": "12345",
    "capabilities": {
      "text": true, "markdown": true, "html": true,
      "images": true, "inline_buttons": true, "commands": true
    }
  }
}
// → Plugin responds:
{
  "result": {
    "text": "All systems operational",
    "html": "All systems <b>operational</b>",
    "buttons": [
      {"label": "Details", "callback_data": "cmd:my-plugin:details"}
    ]
  }
}
```

#### 8. Connector Intents (Host → Plugin)

When a user sends a photo and the plugin handles photo intents:

```jsonc
{
  "method": "connector.intent",
  "params": {
    "scheme": "photo",
    "mime_type": "image/jpeg",
    "data_b64": "/9j/4AAQ...",
    "text": "",
    "metadata": {"width": 1920, "height": 1080},
    "connector_id": "telegram",
    "capabilities": { ... }
  }
}
// → {"result": {"text": "Detected QR code: https://example.com"}}
// → {"result": null}   (pass — plugin doesn't want this intent)
```

#### 9. MCP Tools (Host → Plugin)

```jsonc
// Host → Plugin: execute MCP tool
{
  "method": "mcp.execute",
  "params": {
    "tool_name": "get_system_health",
    "arguments": {}
  }
}
// → {"result": {"content": [{"type": "text", "text": "CPU: 45%"}], "is_error": false}}
```

#### 10. Documents (Host → Plugin)

```jsonc
// Host → Plugin: get dynamic document content
{
  "method": "document.content",
  "params": {"uri": "plugin://my-plugin/health"}
}
// → {"result": {"content": "CPU: 45%, Memory: 62%", "mime_type": "text/plain"}}
```

#### 11. HTTP Routes (Host → Plugin)

Instead of the plugin running its own HTTP server, the host proxies HTTP requests.

```jsonc
// During initialize, plugin declares routes:
{
  "result": {
    "routes": [
      {"method": "GET", "path": "/data"},
      {"method": "POST", "path": "/scan"}
    ]
  }
}

// Host → Plugin: incoming HTTP request
{
  "method": "http.request",
  "params": {
    "method": "POST",
    "path": "/scan",
    "headers": {"content-type": "application/json"},
    "body": "{\"image\": \"base64...\"}"
  }
}
// → {
//   "result": {
//     "status": 200,
//     "headers": {"content-type": "application/json"},
//     "body": "{\"codes\": [\"https://example.com\"]}"
//   }
// }
```

These get mounted at `/api/plugins/{plugin_id}/...` — same as Python plugins.

## Node.js Plugin Structure

### Directory Layout

```
hort/extensions/community/
  my-npm-plugin/
    extension.json          # Same manifest format as Python plugins
    package.json            # npm package manifest
    node_modules/           # Dependencies (gitignored)
    index.js                # Entry point (or index.ts → compiled)
```

### extension.json

Identical format to Python plugins, with one addition:

```json
{
  "name": "whatsapp-connector",
  "version": "0.1.0",
  "description": "WhatsApp messaging via Baileys",
  "runtime": "node",
  "entry_point": "index.js",
  "node_version": ">=22",
  "icon": "ph ph-whatsapp-logo",
  "plugin_type": "connector",
  "capabilities": ["connector", "messaging"],
  "features": {
    "auto_reply": {"description": "Auto-reply to messages", "default": true}
  },
  "ui_script": "static/panel.js"
}
```

The `"runtime": "node"` field (default: `"python"`) tells the registry to launch via the Plugin Host Manager instead of importing in-process.

### package.json

```json
{
  "name": "hort-whatsapp-connector",
  "version": "0.1.0",
  "private": true,
  "main": "index.js",
  "dependencies": {
    "@whiskeysockets/baileys": "^6.0.0",
    "hort-plugin-sdk": "^1.0.0"
  }
}
```

### Plugin SDK (npm package: hort-plugin-sdk)

A thin TypeScript/JS library that handles the JSON-RPC protocol, framing, and provides a typed API identical to the Python `PluginBase`.

```typescript
// hort-plugin-sdk

import { HortPlugin, ConnectorCommand, ConnectorResponse } from 'hort-plugin-sdk';

class WhatsAppConnector extends HortPlugin {

  // Called after host sends "activate"
  async activate(config: Record<string, any>): Promise<void> {
    this.log.info('WhatsApp connector activating...');
    // Use this.config, this.store, this.files — all proxied to host via JSON-RPC
  }

  async deactivate(): Promise<void> {
    this.log.info('Shutting down...');
  }

  // Connector commands
  getConnectorCommands(): ConnectorCommand[] {
    return [
      { name: 'wa_status', description: 'WhatsApp connection status' },
    ];
  }

  async handleConnectorCommand(
    command: string,
    message: IncomingMessage,
    capabilities: ConnectorCapabilities,
  ): Promise<ConnectorResponse> {
    if (command === 'wa_status') {
      return { text: 'WhatsApp: connected' };
    }
    return { text: `Unknown: ${command}` };
  }

  // Scheduled job
  async poll(): Promise<void> {
    const data = await this.fetchSomething();
    await this.store.put('latest', data);
  }
}

// Boot the plugin — connects stdio, runs protocol
HortPlugin.run(WhatsAppConnector);
```

### SDK Internals

```typescript
// hort-plugin-sdk/src/index.ts (simplified)

export abstract class HortPlugin {
  // Proxied APIs — each call sends JSON-RPC to host via stdio
  store: PluginStore;
  files: PluginFileStore;
  config: PluginConfig;
  log: PluginLogger;

  static run(PluginClass: new () => HortPlugin): void {
    const transport = new StdioTransport();      // Content-Length framed JSON-RPC
    const plugin = new PluginClass();
    const bridge = new HostBridge(transport, plugin);

    // Signal ready
    process.stderr.write('HORT_PLUGIN_READY\n');

    // Proxy store/files/config/log to host
    plugin.store = new ProxyStore(transport);     // store.get → JSON-RPC → host → response
    plugin.files = new ProxyFileStore(transport);
    plugin.config = new ProxyConfig(transport);
    plugin.log = new ProxyLogger(transport);

    bridge.listen();  // Block on stdin, dispatch incoming messages
  }
}

class ProxyStore implements PluginStore {
  constructor(private transport: StdioTransport) {}

  async get(key: string): Promise<Record<string, any> | null> {
    return this.transport.request('store.get', { key });
  }

  async put(key: string, value: Record<string, any>, ttlSeconds?: number): Promise<void> {
    await this.transport.request('store.put', { key, value, ttl_seconds: ttlSeconds });
  }

  // ... delete, listKeys, query
}
```

## Plugin Host Manager (Python side)

### Location

```
hort/ext/
  host_manager.py        # NEW: manages out-of-process plugin lifecycle
```

### Responsibilities

1. **Spawn** — launch `node index.js` as a subprocess with stdio pipes
2. **Handshake** — wait for `HORT_PLUGIN_READY` on stderr, send `initialize`
3. **Proxy** — bridge JSON-RPC calls to the real `PluginStore`, `PluginFileStore`, etc.
4. **Supervise** — health checks, auto-restart on crash (exponential backoff: 1s, 2s, 4s, 8s, max 60s)
5. **Route** — forward connector commands, intents, MCP calls, HTTP requests to the right plugin process
6. **Log** — capture stderr, parse structured log messages, forward to hort's rotating logger

### Integration with ExtensionRegistry

```python
# In registry.load_extension():

if manifest.runtime == "node":
    # Launch via host manager instead of importlib
    proxy = host_manager.spawn_plugin(manifest)
    # proxy implements PluginBase interface — same as Python plugins
    # The rest of the system can't tell the difference
    self._instances[manifest.name] = proxy
else:
    # Existing Python path
    module = importlib.import_module(...)
    instance = cls()
    ...
```

### PluginProxy (Python class that looks like a PluginBase)

```python
class PluginProxy(PluginBase, ScheduledMixin, MCPMixin, ConnectorMixin):
    """Python proxy for an out-of-process Node.js plugin.

    Implements the same interface as PluginBase so the rest of hort
    can't tell the difference. All calls are forwarded via JSON-RPC.
    """

    def __init__(self, process: asyncio.subprocess.Process, manifest: ExtensionManifest):
        self._process = process
        self._transport = JsonRpcTransport(process.stdin, process.stdout)
        self._manifest = manifest

    async def activate(self, config: dict) -> None:
        await self._transport.request("activate", {"config": config})

    async def deactivate(self) -> None:
        await self._transport.request("deactivate", {})
        self._process.terminate()

    # MCP — forward to plugin process
    def get_mcp_tools(self) -> list[MCPToolDef]:
        return self._cached_mcp_tools  # from initialize response

    async def execute_mcp_tool(self, tool_name: str, arguments: dict) -> MCPToolResult:
        result = await self._transport.request("mcp.execute", {
            "tool_name": tool_name, "arguments": arguments
        })
        return MCPToolResult(**result)

    # Connector — forward to plugin process
    async def handle_connector_command(self, command, message, capabilities):
        result = await self._transport.request("connector.command", {
            "command": command, ...
        })
        return ConnectorResponse(**result)

    # Scheduler — host manages timer, calls plugin when it fires
    # (job definitions come from initialize response)
```

### Handling Plugin → Host Calls

When the Node plugin calls `this.store.get("key")`, the SDK sends a JSON-RPC request to the host. The host needs to handle these **while also sending its own requests** to the plugin. This is bidirectional.

```python
class JsonRpcTransport:
    """Bidirectional JSON-RPC over stdio with Content-Length framing."""

    async def _read_loop(self):
        """Continuously read messages from plugin stdout."""
        while True:
            msg = await self._read_message()
            if "id" in msg and "method" in msg:
                # Plugin → Host request (store.get, files.save, etc.)
                result = await self._handle_plugin_request(msg)
                await self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            elif "id" in msg and "result" in msg:
                # Response to a Host → Plugin request
                self._pending[msg["id"]].set_result(msg["result"])
            elif "method" in msg and "id" not in msg:
                # Notification (log messages)
                self._handle_notification(msg)

    async def _handle_plugin_request(self, msg: dict) -> Any:
        method = msg["method"]
        params = msg.get("params", {})

        if method == "store.get":
            return await self._store.get(params["key"])
        elif method == "store.put":
            await self._store.put(params["key"], params["value"], params.get("ttl_seconds"))
            return {"ok": True}
        elif method == "files.save":
            data = base64.b64decode(params["data_b64"])
            uri = await self._files.save(params["name"], data, params.get("mime_type", ""))
            return {"uri": uri}
        elif method == "log":
            self._logger.log(params["level"], params["message"])
            return None
        # ... etc
```

## Discovery & Installation

### Python Plugins (unchanged)

```
hort/extensions/core/my-plugin/
  extension.json
  provider.py
```

### Node.js Plugins

```
hort/extensions/community/my-npm-plugin/
  extension.json            # runtime: "node"
  package.json
  index.js
```

### Installation Flow

```bash
# Install a community Node.js plugin
cd hort/extensions/community/
git clone https://github.com/user/hort-whatsapp-connector.git
cd hort-whatsapp-connector
npm install

# Or eventually via a CLI:
hort plugin install hort-whatsapp-connector
```

The registry discovers it the same way — scans for `extension.json`, sees `"runtime": "node"`, routes to the host manager.

### npm install Isolation

Each plugin has its own `node_modules/`. No shared dependencies. This prevents version conflicts between plugins. The tradeoff is disk space, but node_modules is already absurd so it doesn't matter.

## Process Supervision

### Health Checks

Every 30 seconds, the host sends `{"method": "health"}`. If no response within 5 seconds:

1. Log warning
2. Send SIGTERM
3. Wait 3 seconds
4. Send SIGKILL if still alive
5. Restart with exponential backoff (1s, 2s, 4s, 8s, 16s, 32s, max 60s)
6. After 5 consecutive crashes within 5 minutes: mark plugin as failed, stop retrying, log error

### Resource Limits

On Linux, use cgroups v2 (via systemd or direct):
- `MemoryMax=256M` per plugin (configurable in extension.json)
- `CPUQuota=50%` default

On macOS, no cgroups. Use `ulimit` in the subprocess or accept that macOS is a dev environment.

### Graceful Shutdown

```
1. Host sends "deactivate" request
2. Wait 5 seconds for response
3. Close stdin (signals EOF to plugin)
4. Wait 3 seconds for process exit
5. SIGTERM
6. Wait 2 seconds
7. SIGKILL
```

## UI Integration

Node.js plugins provide UI the exact same way as Python plugins — via `static/panel.js` that extends `HortExtension`. The UI is always browser-side JavaScript regardless of backend language. No change needed.

```
my-npm-plugin/
  extension.json        # ui_script: "static/panel.js"
  static/
    panel.js            # HortExtension subclass (Vue component)
  index.js              # Node.js backend
  package.json
```

The host serves the `static/` directory at `/ext/my_npm_plugin/static/` — same path pattern as Python plugins.

## What Changes vs What Stays the Same

### Stays the Same (Zero changes)

- `extension.json` manifest format (just add `runtime` field)
- UI panel architecture (`HortExtension`, `panel.js`)
- Store/FileStore/Config APIs (same interface, proxied for Node)
- MCP tool registration and execution
- Intent handling
- Document provision
- Connector command interface
- Admin API (`/api/plugins`, feature toggles, etc.)
- Scheduler job definitions

### New Components

| Component | Location | Purpose |
|---|---|---|
| `PluginHostManager` | `hort/ext/host_manager.py` | Spawn, supervise, restart Node processes |
| `JsonRpcTransport` | `hort/ext/jsonrpc.py` | Content-Length framed bidirectional JSON-RPC |
| `PluginProxy` | `hort/ext/proxy.py` | Python shim that implements PluginBase, forwards to process |
| `hort-plugin-sdk` | `npm` package | Node.js SDK — HortPlugin base class, stdio transport, typed API |

### Registry Changes (minimal)

```python
# In ExtensionRegistry.load_extension():
if manifest.runtime == "node":
    proxy = await host_manager.spawn_plugin(manifest, context)
    self._instances[manifest.name] = proxy
else:
    # existing Python path unchanged
```

## Concrete Example: WhatsApp Connector as Node.js Plugin

```
hort/extensions/community/whatsapp_connector/
  extension.json
  package.json
  index.js
  static/
    panel.js           # QR code display for WhatsApp pairing
```

**extension.json:**
```json
{
  "name": "whatsapp-connector",
  "version": "0.1.0",
  "description": "WhatsApp messaging via Baileys",
  "runtime": "node",
  "entry_point": "index.js",
  "node_version": ">=22",
  "provider": "community",
  "platforms": ["darwin", "linux"],
  "capabilities": ["connector", "messaging"],
  "icon": "ph ph-whatsapp-logo",
  "plugin_type": "connector",
  "features": {
    "auto_connect": {"description": "Connect on startup", "default": true}
  },
  "ui_script": "static/panel.js"
}
```

**index.js:**
```javascript
const { HortPlugin } = require('hort-plugin-sdk');
const { makeWASocket, useMultiFileAuthState } = require('@whiskeysockets/baileys');

class WhatsAppConnector extends HortPlugin {

  async activate(config) {
    this.log.info('WhatsApp connector starting...');

    // Auth state persisted in plugin's file store
    const authDir = config.auth_dir || '/tmp/hort-wa-auth';
    const { state, saveCreds } = await useMultiFileAuthState(authDir);

    this.socket = makeWASocket({ auth: state });
    this.socket.ev.on('creds.update', saveCreds);

    this.socket.ev.on('connection.update', async (update) => {
      if (update.qr) {
        // Store QR for the UI panel to display
        await this.store.put('qr', { qr: update.qr, ts: Date.now() });
      }
      if (update.connection === 'open') {
        await this.store.put('status', { connected: true, ts: Date.now() });
        this.log.info('WhatsApp connected');
      }
    });

    this.socket.ev.on('messages.upsert', async ({ messages }) => {
      for (const msg of messages) {
        if (msg.key.fromMe) continue;
        // Forward to connector dispatch (handled by host)
        // The host will route this to registered command handlers
      }
    });
  }

  async deactivate() {
    if (this.socket) this.socket.end();
  }

  getConnectorCommands() {
    return [
      { name: 'wa_status', description: 'WhatsApp connection status' },
      { name: 'wa_qr', description: 'Show pairing QR code' },
    ];
  }

  async handleConnectorCommand(command, message, capabilities) {
    if (command === 'wa_status') {
      const status = await this.store.get('status');
      return { text: status?.connected ? 'Connected' : 'Disconnected' };
    }
    if (command === 'wa_qr') {
      const qr = await this.store.get('qr');
      return { text: qr ? `Scan this QR:\n${qr.qr}` : 'No QR available — already connected?' };
    }
    return { text: `Unknown: ${command}` };
  }
}

HortPlugin.run(WhatsAppConnector);
```

This is a full WhatsApp connector that:
- Uses Baileys (only available in npm)
- Shares the same store/config/log APIs as Python plugins
- Registers connector commands
- Provides a UI panel for QR code display
- The hort server can't tell it's running in a different process/language

## Implementation Order

1. **`hort/ext/jsonrpc.py`** — Content-Length framed bidirectional JSON-RPC transport
2. **`hort/ext/host_manager.py`** — Process spawn, health check, restart loop
3. **`hort/ext/proxy.py`** — PluginProxy that implements PluginBase
4. **Registry integration** — `runtime` field check in `load_extension()`
5. **`hort-plugin-sdk`** (npm) — HortPlugin base, ProxyStore, ProxyConfig, StdioTransport
6. **Test plugin** — simple Node.js echo plugin to validate the protocol end-to-end
7. **WhatsApp connector** — real-world proof that it works

Steps 1-4 are Python-only (no Node changes). Step 5 is the SDK. Steps 6-7 are validation.
