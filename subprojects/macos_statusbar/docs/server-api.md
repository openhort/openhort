# Server API

## Overview

The status bar is a client of the openhort server. It needs to answer these questions on every poll cycle:

1. Is the server alive?
2. How many viewers are connected, and who are they?
3. What targets are registered?
4. What are the plugins reporting?

This document specifies every endpoint the status bar uses — both existing endpoints it can reuse today, and new endpoints needed for full functionality.

## Polling Strategy

### Poll Cycle

The status bar runs a single poll cycle every **3 seconds**. Each cycle makes one HTTP request to a combined endpoint that returns everything:

```
Every 3 seconds:
  GET /api/statusbar/state
  → {server, viewers, targets, plugins}
  → Update menu, icon, overlay
```

### Why 3 Seconds?

| Interval | Tradeoff |
|----------|----------|
| 1s | Too aggressive — 1 req/s to localhost is fine for CPU but rebuilds the menu too often, causing flicker if the menu is open |
| 3s | Good balance — viewer connects are surfaced within 3 seconds, server load is negligible |
| 5s | Acceptable but sluggish — a viewer could watch for 5 seconds before the icon turns red |
| 10s | Too slow for a privacy indicator |

3 seconds means the worst case for the viewing indicator is: a viewer connects, and the machine owner sees the red dot 3 seconds later. This is fast enough to be considered "immediate" for human perception.

### Fallback Polling (Phase 1, before combined endpoint)

Before the combined endpoint is implemented, the status bar uses multiple existing endpoints:

```
Every 3 seconds:
  1. GET /api/hash                           → server alive? (existing)
  2. POST /api/session                       → create temp session (existing)
  3. WS /ws/control/{session_id}             → send get_status, recv observer_count (existing)
  4. Close WS
```

This is more expensive (creates a session per poll cycle) but works with the server as-is, no changes needed.

## Existing Endpoints Used

### `GET /api/hash`

**Purpose**: Health check. Returns static content hash + dev mode flag.

**Response**:
```json
{"hash": "a1b2c3d4e5f6", "dev": "0"}
```

**Status bar usage**: If this returns 200, the server is alive. If connection refused or timeout, the server is down.

**Cost**: Negligible — reads cached hash, no I/O.

### `POST /api/session`

**Purpose**: Create a viewer session.

**Response**:
```json
{"session_id": "uuid-here"}
```

**Status bar usage (Phase 1)**: Creates a temporary session to use the control WebSocket for status queries. The session is short-lived — the WS connects, sends `get_status`, gets the response, and disconnects.

**Note**: This creates an entry in the session registry. The session is cleaned up when the WS disconnects. In Phase 2, the combined endpoint eliminates this overhead.

### `GET /api/connectors`

**Purpose**: Get connector info (LAN IP, ports, cloud tunnel status, messaging connectors).

**Response** (partial):
```json
{
  "lan": {
    "ip": "192.168.1.42",
    "http_port": 8940,
    "https_port": 8950,
    "http_url": "http://192.168.1.42:8940",
    "https_url": "https://192.168.1.42:8950",
    "qr_url": "data:image/png;base64,..."
  },
  "cloud": {
    "active": true,
    "server_url": "https://openhort-access.azurewebsites.net",
    "host_id": "abc123"
  },
  "connectors": [
    {"type": "telegram", "status": "running", "bot_username": "openhort_bot"}
  ]
}
```

**Status bar usage**: Extracts LAN IP and URL for the status header and "Copy URL" / "Open in Browser" actions.

### `GET /api/plugins`

**Purpose**: List all loaded plugins with their manifests.

**Response** (partial):
```json
[
  {
    "id": "network-monitor",
    "name": "Network Monitor",
    "version": "0.1.0",
    "manifest": {
      "statusbar": {
        "priority": 40,
        "icon": "ph-wifi-high",
        "items": [...],
        "actions": [...]
      }
    },
    "status": "active"
  }
]
```

**Status bar usage**: Discovers which plugins have `statusbar` contributions. Called once on startup and whenever plugins change (detected by list length changing on poll).

### `GET /api/plugins/{id}/status`

**Purpose**: Get a plugin's in-memory status.

**Response** (plugin-defined):
```json
{
  "latest": {"tx_rate": 2400000, "rx_rate": 460000},
  "history": [...],
  "statusbar": {
    "upload": "2.3 MB/s",
    "download": "450 KB/s",
    "monitoring_active": true
  }
}
```

**Status bar usage**: Extracts the `statusbar` key for template interpolation and toggle states.

### `GET /api/qr`

**Purpose**: Generate a QR code data URI for a given URL.

**Query params**: `?url=https://192.168.1.42:8950`

**Response**:
```json
{"qr": "data:image/png;base64,..."}
```

**Status bar usage**: Powers the "Show QR Code…" popup window.

### `GET /api/debug/memory`

**Purpose**: Memory diagnostics.

**Response**:
```json
{
  "rss_mb": 142.3,
  "gc_objects": 48231,
  "asyncio_tasks": 12,
  "top_types": [...]
}
```

**Status bar usage**: Powers the "Show Debug Info" action in Settings.

## New Endpoints Required

### `GET /api/statusbar/state`

**Purpose**: Combined endpoint that returns everything the status bar needs in a single request. This is the primary poll target in Phase 2+.

**Response**:
```json
{
  "server": {
    "running": true,
    "version": "0.1.0",
    "uptime_seconds": 3621,
    "lan_ip": "192.168.1.42",
    "http_port": 8940,
    "https_port": 8950,
    "https_url": "https://192.168.1.42:8950",
    "dev_mode": false
  },
  "viewers": [
    {
      "session_id": "abc-123",
      "observer_id": 1,
      "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0...",
      "device": "iPhone (Safari)",
      "active_window": "Desktop",
      "target_id": "local-macos",
      "connected_at": "2026-03-28T14:30:00Z",
      "streaming": true
    },
    {
      "session_id": "def-456",
      "observer_id": 2,
      "user_agent": "Mozilla/5.0 (iPad; CPU OS 18_0...",
      "device": "iPad (Chrome)",
      "active_window": "Terminal (zsh)",
      "target_id": "local-macos",
      "connected_at": "2026-03-28T14:38:00Z",
      "streaming": true
    }
  ],
  "targets": [
    {"id": "local-macos", "name": "This Mac", "provider_type": "macos", "status": "available"},
    {"id": "docker-linux-1", "name": "Linux (openhort-linux-desktop)", "provider_type": "linux-docker", "status": "available"}
  ],
  "plugins": [
    {
      "id": "network-monitor",
      "statusbar_data": {
        "upload": "2.3 MB/s",
        "download": "450 KB/s",
        "monitoring_active": true
      }
    },
    {
      "id": "telegram-connector",
      "statusbar_data": {
        "status": "Running",
        "bot_username": "openhort_bot",
        "screenshots_enabled": true
      }
    }
  ]
}
```

**Implementation notes**:

- The `viewers` array is built from the session registry — iterate active sessions, filter those with a `stream_ws` (actively streaming)
- The `device` field is parsed from User-Agent on the server side (not by the status bar) to keep the response simple
- The `plugins` array calls `get_status()` on each plugin that has a `statusbar` manifest key, extracts only the `statusbar` sub-dict
- Plugins that don't have `statusbar` in their manifest are excluded
- Plugins whose `get_status()` raises are included with `"statusbar_data": null` and an `"error"` field
- Total response size is small (~1-3 KB for typical setups)

**Server-side implementation** (sketch):

```python
@app.get("/api/statusbar/state")
async def statusbar_state():
    registry = HortRegistry.get()
    target_registry = TargetRegistry.get()
    ext_registry = get_extension_registry()

    # Server info
    server = {
        "running": True,
        "version": __version__,
        "uptime_seconds": int(time.time() - _start_time),
        "lan_ip": _server_info.lan_ip,
        "http_port": HTTP_PORT,
        "https_port": HTTPS_PORT,
        "https_url": _server_info.https_url,
        "dev_mode": DEV_MODE,
    }

    # Active viewers
    viewers = []
    for sid, entry in registry.items():
        if entry.stream_ws:
            viewers.append({
                "session_id": sid,
                "observer_id": entry.observer_id,
                "user_agent": getattr(entry, "user_agent", ""),
                "device": _parse_device(getattr(entry, "user_agent", "")),
                "active_window": _window_name(entry),
                "target_id": entry.active_target_id,
                "connected_at": getattr(entry, "connected_at", ""),
                "streaming": True,
            })

    # Targets
    targets = [
        {"id": t.id, "name": t.name, "provider_type": t.provider_type, "status": t.status}
        for t in target_registry.list_targets()
    ]

    # Plugin statusbar data
    plugins = []
    for plugin_id, ctx in ext_registry.plugin_contexts():
        manifest = ctx.manifest
        if not manifest.get("statusbar"):
            continue
        plugin = ctx.plugin
        try:
            status = plugin.get_status() if hasattr(plugin, "get_status") else {}
            statusbar_data = status.get("statusbar")
        except Exception as e:
            statusbar_data = None
        plugins.append({"id": plugin_id, "statusbar_data": statusbar_data})

    return {"server": server, "viewers": viewers, "targets": targets, "plugins": plugins}
```

### `POST /api/sessions/disconnect-all`

**Purpose**: Disconnect all active stream viewers. This is the "panic button."

**Request body**: None.

**Response**:
```json
{"disconnected": 2}
```

**Implementation**: Iterates all sessions, closes each `stream_ws` with WebSocket close code 4003 ("disconnected by host"), sets `stream_config = None`.

```python
@app.post("/api/sessions/disconnect-all")
async def disconnect_all():
    registry = HortRegistry.get()
    count = 0
    for sid, entry in list(registry.items()):
        if entry.stream_ws:
            try:
                await entry.stream_ws.close(code=4003, reason="Disconnected by host")
            except Exception:
                pass
            entry.stream_config = None
            entry.stream_ws = None
            count += 1
    return {"disconnected": count}
```

### `DELETE /api/sessions/{session_id}` (Future, Phase 4)

**Purpose**: Disconnect a specific viewer.

**Response**:
```json
{"ok": true, "session_id": "abc-123"}
```

### `GET /api/targets`

**Purpose**: List registered targets. A lighter-weight alternative to using the WebSocket `list_targets` message.

**Response**:
```json
[
  {"id": "local-macos", "name": "This Mac", "provider_type": "macos", "status": "available"},
  {"id": "docker-linux-1", "name": "Linux (openhort-linux-desktop)", "provider_type": "linux-docker", "status": "available"}
]
```

**Note**: This endpoint may already be served by the combined `/api/statusbar/state`. It's listed separately for completeness — if the combined endpoint exists, this standalone endpoint is optional.

### `POST /api/plugins/{plugin_id}/action`

**Purpose**: Dispatch a status bar action to a plugin.

**Request**:
```json
{
  "action": "toggle_monitoring",
  "args": {}
}
```

**Response** (success):
```json
{
  "ok": true,
  "result": {"monitoring_active": false}
}
```

**Response** (error):
```json
{
  "ok": false,
  "error": "Unknown action: foobar"
}
```

**Implementation**: Looks up the plugin, calls `handle_statusbar_action(action, args)`, returns the result.

## Error Handling

### Connection Refused

The server is not running. `httpx.ConnectError` is caught.

```python
try:
    resp = await self._http.get(f"http://localhost:{HTTP_PORT}/api/statusbar/state")
except httpx.ConnectError:
    self._status.running = False
    self._status.observers = 0
```

Status bar shows: "Server: Stopped" with gray icon.

### Timeout

The server is running but not responding (busy, deadlocked, or overloaded). `httpx.TimeoutException` is caught.

```python
try:
    resp = await self._http.get(..., timeout=5.0)
except httpx.TimeoutException:
    self._timeout_count += 1
    if self._timeout_count >= 3:
        self._status.error = "Server not responding"
```

Status bar shows: "Server: Not Responding" with yellow icon. The timeout counter prevents a single slow response from triggering the warning — three consecutive timeouts are needed.

### HTTP Errors

The server responds but with an error status code.

```python
if resp.status_code == 401:
    self._status.error = "Authentication required"
elif resp.status_code >= 500:
    self._status.error = f"Server error ({resp.status_code})"
```

401 can happen if `LLMING_AUTH_SECRET` is set and the status bar doesn't provide it. The status bar should read the auth secret from the `.env` file in the project root.

### Malformed Response

The server returns invalid JSON or an unexpected schema.

```python
try:
    data = resp.json()
    self._status.observers = len(data.get("viewers", []))
except (json.JSONDecodeError, KeyError, TypeError):
    # Keep previous status, log the error
    logger.warning("Malformed response from /api/statusbar/state")
```

The status bar never crashes on a malformed response. It keeps the last known good state and logs a warning.

## Authentication

If the server has `LLMING_AUTH_SECRET` set, API calls require authentication. The status bar reads the secret from the project's `.env` file:

```python
def _load_auth_secret(self) -> str | None:
    env_file = self._project_root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("LLMING_AUTH_SECRET="):
                return line.split("=", 1)[1].strip()
    return None
```

The secret is passed as a query parameter or header on each request:

```python
headers = {}
if self._auth_secret:
    headers["Authorization"] = f"Bearer {self._auth_secret}"
```

## Bandwidth Estimate

Per poll cycle (every 3 seconds):
- Request: ~200 bytes (GET with headers)
- Response: ~2 KB (typical, with 2 viewers, 2 targets, 4 plugins)
- Total: ~2.2 KB per cycle
- Per minute: ~44 KB
- Per hour: ~2.6 MB

This is negligible for localhost communication. No optimization needed.

## WebSocket vs HTTP Polling

An alternative to HTTP polling is maintaining a persistent WebSocket connection to the control channel and subscribing to status updates. This would give sub-second notification of viewer connects/disconnects.

**Why HTTP polling was chosen instead**:

| Factor | HTTP Polling | WebSocket |
|--------|-------------|-----------|
| Simplicity | One GET per cycle, stateless | Must manage connection lifecycle, reconnects, heartbeats |
| Server impact | One request per 3s | One persistent connection consuming a session slot |
| Latency | 0-3s to detect changes | <100ms |
| Resilience | Each request is independent; if one fails, next one works | Connection drop needs reconnect logic |
| Session pollution | No session created (combined endpoint is sessionless) | Creates a permanent session in the registry |

3-second latency is acceptable for all use cases. The status bar doesn't need sub-second updates. HTTP polling is dramatically simpler and more robust.

**Future consideration**: If sub-second viewer notification becomes important (e.g., for the Tier 3 notification to fire instantly), we could add a lightweight Server-Sent Events (SSE) endpoint that pushes only observer_count changes. This would be one persistent HTTP connection with minimal overhead, avoiding the complexity of WebSocket lifecycle management.
