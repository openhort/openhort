# Plugin Contributions

## Overview

Plugins can contribute items to the macOS status bar menu without touching any status bar code. The mechanism follows the same pattern as openhort's browser-side plugin UI: declare in manifest, provide data via `get_status()`, handle actions via a dispatch method.

The status bar app discovers plugin contributions by reading the `statusbar` key from each plugin's manifest (via `GET /api/plugins`), then polls each plugin's status endpoint to populate dynamic values.

## Manifest Declaration

A plugin declares its status bar presence in `extension.json` under a top-level `statusbar` key:

```json
{
  "name": "network-monitor",
  "version": "0.1.0",
  "entry_point": "provider:NetworkMonitor",

  "statusbar": {
    "priority": 50,
    "icon": "ph-wifi-high",
    "items": [ ... ],
    "actions": [ ... ],
    "submenu": false
  }
}
```

### Top-Level Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `priority` | `int` | `100` | Sort order in the Plugins section. Lower = higher in menu. |
| `icon` | `string` | `null` | Phosphor icon class (e.g., `ph-wifi-high`). Mapped to emoji for NSMenu. |
| `items` | `array` | `[]` | Status display items (live text, labels). |
| `actions` | `array` | `[]` | Clickable items (toggles, buttons, links). |
| `submenu` | `bool` | `false` | If `true`, all items and actions are grouped under a submenu named after the plugin. If `false`, items appear inline in the Plugins section. |

### When to Use a Submenu

- **Inline** (default): Best for plugins with 1-2 items. Keeps the menu compact. Most plugins should use this.
- **Submenu**: Best for plugins with 3+ items or actions. Prevents the main menu from getting too long. The submenu header shows the plugin's primary status line.

## Item Types

### `live_status` — Dynamic Text

A non-clickable menu item whose text updates on every poll cycle.

```json
{
  "id": "bandwidth",
  "type": "live_status",
  "label": "Network: {upload} ↑  {download} ↓",
  "icon": "ph-wifi-high",
  "refresh_seconds": 5
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | Yes | Unique within this plugin. Used to look up data in the status dict. |
| `type` | `string` | Yes | `"live_status"` |
| `label` | `string` | Yes | Template string. `{placeholder}` values are interpolated from the plugin's `statusbar` status dict. |
| `icon` | `string` | No | Override icon for this item (defaults to plugin-level icon). |
| `refresh_seconds` | `int` | No | How often the server should re-call `get_status()` for this plugin. Default: 10. |

**Template interpolation**: The `{placeholder}` syntax uses Python's `str.format_map()` against the plugin's `statusbar` status dict. If a placeholder key is missing, it renders as `--` (not an error).

**Examples**:

```
Label template:                  Status dict:                     Rendered:
"Network: {upload} ↑ {down} ↓"  {"upload": "2.3 MB/s",          "Network: 2.3 MB/s ↑ 450 KB/s ↓"
                                  "down": "450 KB/s"}

"CPU: {temp}°C"                  {"temp": "67"}                   "CPU: 67°C"

"Clipboard: {count} items"       {"count": "12"}                  "Clipboard: 12 items"

"Bot: {status}"                  {"status": "Running"}            "Bot: Running"

"P2P: {tunnels} tunnel(s)"      {}  (key missing)                "P2P: -- tunnel(s)"
```

### `static_label` — Fixed Text

A non-clickable, grayed-out informational line. Not interpolated — the text is static from the manifest.

```json
{
  "id": "bot_name",
  "type": "static_label",
  "label": "Bot: @openhort_bot"
}
```

Useful for showing fixed configuration like bot usernames, server addresses, or version numbers. The text can still reference status data if the plugin wants to change it at runtime — but `live_status` is more appropriate for that.

### `toggle` — Checkmark Toggle

A clickable item with a checkmark that reflects boolean state. Clicking calls a plugin method to flip the state.

```json
{
  "id": "toggle-monitoring",
  "type": "toggle",
  "label": "Pause Monitoring",
  "toggle_label": "Resume Monitoring",
  "method": "toggle_monitoring",
  "state_key": "monitoring_active"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | `string` | Yes | Label when state is ON (checkmark shown). |
| `toggle_label` | `string` | No | Label when state is OFF. If omitted, same label is used for both states. |
| `method` | `string` | Yes | Python method name on the plugin class to call when clicked. |
| `state_key` | `string` | Yes | Key in the plugin's `statusbar` status dict. Must be a boolean. |

**Rendering**:
- `state_key` is `true` → checkmark shown, `label` displayed
- `state_key` is `false` → no checkmark, `toggle_label` displayed (or `label` if no `toggle_label`)

**Click behavior**: Calls `POST /api/plugins/{plugin_id}/action` with `{"action": "toggle_monitoring"}`. The plugin toggles its internal state. The next poll cycle picks up the new `state_key` value and updates the menu.

### `action` — Button

A clickable item that triggers a plugin method. No checkmark, no toggle — it's a one-shot action.

```json
{
  "id": "clear-history",
  "type": "action",
  "label": "Clear Clipboard History",
  "method": "clear_history",
  "confirm": "Clear all clipboard entries?"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | `string` | Yes | Menu item text. |
| `method` | `string` | Yes | Plugin method to call. |
| `confirm` | `string` | No | If set, show an NSAlert with this message before executing. |

**Click behavior**: If `confirm` is set, show a confirmation alert. If confirmed (or no `confirm`), call `POST /api/plugins/{plugin_id}/action` with `{"action": "clear_history"}`.

### `link` — Open URL

A clickable item that opens a URL in the default browser. No server call — purely client-side.

```json
{
  "id": "open-chat",
  "type": "link",
  "label": "Open Bot Chat…",
  "url": "https://t.me/{bot_username}"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | `string` | Yes | Menu item text. Trailing `…` recommended (macOS convention). |
| `url` | `string` | Yes | URL to open. Supports `{placeholder}` interpolation from status dict. |

## Data Protocol

### Providing Status Bar Data

Plugins provide data for their status bar items through the existing `get_status()` method. The status bar app reads the `statusbar` key:

```python
class NetworkMonitor(PluginBase):
    def activate(self, config: dict) -> None:
        self._latest = {}
        self._monitoring = True

    def get_status(self) -> dict:
        return {
            # Existing keys — used by browser UI
            "latest": self._latest,
            "history": self._history,

            # New key — used by macOS status bar
            "statusbar": {
                # Values for live_status template interpolation
                "upload": format_bytes(self._latest.get("tx_rate", 0)),
                "download": format_bytes(self._latest.get("rx_rate", 0)),

                # Values for toggle state_keys
                "monitoring_active": self._monitoring,
            },
        }
```

### Rules for `statusbar` Data

1. **All values must be strings or booleans.** The status bar doesn't interpret numbers, lists, or nested objects. The plugin is responsible for formatting values into human-readable strings.

2. **Keys map to item IDs and state_keys.** A `live_status` item with `"label": "Net: {upload}"` looks for `statusbar["upload"]`. A toggle with `"state_key": "monitoring_active"` looks for `statusbar["monitoring_active"]`.

3. **Missing keys render as `--`.** If a `live_status` template references a key that doesn't exist in the status dict, it renders as `--` (two dashes). This is a safe fallback, not an error.

4. **No disk I/O in `get_status()`.** The existing rule applies: `get_status()` returns in-memory data only. The status bar polls frequently (every 3-10 seconds) — disk I/O would be wasteful.

5. **Flat dict only.** The `statusbar` dict is flat — no nested objects. Keys should be short, descriptive identifiers. The manifest template handles formatting.

## Action Protocol

### Endpoint

```
POST /api/plugins/{plugin_id}/action
Content-Type: application/json

{
  "action": "toggle_monitoring",
  "args": {}
}
```

Response:

```json
{
  "ok": true,
  "result": {
    "monitoring_active": false
  }
}
```

### Plugin Implementation

Plugins handle status bar actions by implementing `handle_statusbar_action`:

```python
class NetworkMonitor(PluginBase):
    async def handle_statusbar_action(self, action: str, args: dict) -> dict:
        if action == "toggle_monitoring":
            self._monitoring = not self._monitoring
            return {"monitoring_active": self._monitoring}

        if action == "reset_stats":
            self._history.clear()
            self._latest = {}
            return {"reset": True}

        raise ValueError(f"Unknown action: {action}")
```

**Return value**: A dict that gets merged into the immediate response. The status bar can use this to update the menu immediately without waiting for the next poll cycle.

**Error handling**: If the method raises, the endpoint returns `{"ok": false, "error": "message"}`. The status bar shows a brief alert.

### Server-Side Dispatch

The new endpoint in `hort/app.py` or `hort/plugins.py`:

```python
@app.post("/api/plugins/{plugin_id}/action")
async def plugin_action(plugin_id: str, body: dict):
    plugin = registry.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(404, f"Plugin {plugin_id} not found")
    if not hasattr(plugin, "handle_statusbar_action"):
        raise HTTPException(400, f"Plugin {plugin_id} doesn't support actions")

    try:
        result = await plugin.handle_statusbar_action(body["action"], body.get("args", {}))
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

## Rendering Rules

### Plugin Section Layout

The status bar renders the Plugins section as follows:

```
─── Plugins ───                    ← section header (disabled, dim)
🌐 Network: ↑ 2.3 MB/s ↓ 450 KB  ← inline plugin (no submenu)
📡 Telegram ▸                      ← submenu plugin
   Bot: Running
   Open Bot Chat…
🔗 P2P: 1 active tunnel           ← inline plugin
📋 Clipboard ▸                     ← submenu plugin
   12 items captured
   ✓ Capture Enabled
   Clear History
```

### Ordering

1. Plugins are sorted by `statusbar.priority` (ascending). Lower number = higher in menu.
2. Plugins with the same priority are sorted alphabetically by plugin name.
3. Suggested priority ranges:
   - 0-30: Connectivity (P2P, Telegram, Cloud) — most important for status bar
   - 31-60: Monitors (Network, System, Disk) — live data
   - 61-90: Tools (Clipboard, Screen Watcher) — utility
   - 91+: Everything else

### Icon Mapping

Plugin manifests use Phosphor icon class names (e.g., `ph-wifi-high`). Since NSMenu items can't render web font icons, the status bar maps them to emoji:

| Phosphor class | Emoji | Category |
|---------------|-------|----------|
| `ph-wifi-high` | 🌐 | Network |
| `ph-telegram-logo` | 📡 | Messaging |
| `ph-link` | 🔗 | Connectivity |
| `ph-clipboard` | 📋 | Utility |
| `ph-chart-bar` | 📊 | Monitoring |
| `ph-cpu` | ⚡ | System |
| `ph-hard-drives` | 💾 | Storage |
| `ph-eye` | 👁 | Viewing |
| `ph-terminal` | ⬛ | Terminal |
| `ph-camera` | 📷 | Camera |
| (unknown) | ▪ | Fallback |

The mapping is a static dict in the status bar code. Plugins can also specify a literal emoji in the `icon` field (e.g., `"icon": "📡"`), which is used directly.

### Disabled State

When the server is stopped, all plugin items are shown as disabled (grayed out) with their last known text. This is better than hiding them entirely — the user can still see which plugins are configured.

When a specific plugin fails to respond (its `/status` endpoint returns an error), only that plugin's items are disabled, with text like "Network Monitor: Error".

## Full Examples

### Network Monitor

**Manifest** (`hort/extensions/core/network_monitor/extension.json`):
```json
{
  "name": "network-monitor",
  "statusbar": {
    "priority": 40,
    "icon": "ph-wifi-high",
    "items": [
      {
        "id": "bandwidth",
        "type": "live_status",
        "label": "Net: {upload} ↑  {download} ↓",
        "refresh_seconds": 5
      }
    ],
    "actions": [
      {
        "id": "toggle-monitoring",
        "type": "toggle",
        "label": "Monitoring Active",
        "toggle_label": "Monitoring Paused",
        "method": "toggle_monitoring",
        "state_key": "monitoring_active"
      }
    ]
  }
}
```

**Status dict**:
```python
{"statusbar": {"upload": "2.3 MB/s", "download": "450 KB/s", "monitoring_active": True}}
```

**Rendered** (inline, no submenu):
```
🌐 Net: 2.3 MB/s ↑  450 KB/s ↓
   ✓ Monitoring Active
```

### Telegram Connector

**Manifest**:
```json
{
  "name": "telegram-connector",
  "statusbar": {
    "priority": 10,
    "icon": "📡",
    "submenu": true,
    "items": [
      {"id": "status", "type": "live_status", "label": "Bot: {status}", "refresh_seconds": 10},
      {"id": "username", "type": "static_label", "label": "@{bot_username}"}
    ],
    "actions": [
      {"id": "open-chat", "type": "link", "label": "Open Bot Chat…", "url": "https://t.me/{bot_username}"},
      {"id": "toggle-screenshots", "type": "toggle", "label": "Screenshots Enabled", "method": "toggle_screenshots", "state_key": "screenshots_enabled"}
    ]
  }
}
```

**Status dict**:
```python
{"statusbar": {"status": "Running", "bot_username": "openhort_bot", "screenshots_enabled": True}}
```

**Rendered** (submenu):
```
📡 Telegram Bot: Running ▸
   ┌──────────────────────────────┐
   │  Bot: Running                │
   │  @openhort_bot               │
   │  ───────────                 │
   │  Open Bot Chat…              │
   │  ✓ Screenshots Enabled       │
   └──────────────────────────────┘
```

The submenu header (on the parent menu) shows the first `live_status` item's rendered text, prefixed with the icon.

### P2P Extension

**Manifest**:
```json
{
  "name": "peer2peer",
  "statusbar": {
    "priority": 15,
    "icon": "🔗",
    "items": [
      {"id": "tunnels", "type": "live_status", "label": "P2P: {active_count} active"}
    ],
    "actions": [
      {"id": "generate-link", "type": "action", "label": "Generate Connect Link…", "method": "generate_link"}
    ]
  }
}
```

**Rendered** (inline):
```
🔗 P2P: 1 active
   Generate Connect Link…
```

### Clipboard History

**Manifest**:
```json
{
  "name": "clipboard-history",
  "statusbar": {
    "priority": 70,
    "icon": "📋",
    "submenu": true,
    "items": [
      {"id": "count", "type": "live_status", "label": "Clipboard: {count} items"}
    ],
    "actions": [
      {"id": "toggle-capture", "type": "toggle", "label": "Capture Enabled", "toggle_label": "Capture Paused", "method": "toggle_capture", "state_key": "capturing"},
      {"id": "clear", "type": "action", "label": "Clear History", "method": "clear_history", "confirm": "Delete all clipboard entries?"}
    ]
  }
}
```

**Rendered** (submenu):
```
📋 Clipboard: 12 items ▸
   ┌──────────────────────────────────┐
   │  Clipboard: 12 items             │
   │  ───────────                     │
   │  ✓ Capture Enabled               │
   │  Clear History                    │
   └──────────────────────────────────┘
```

### System Monitor

**Manifest**:
```json
{
  "name": "system-monitor",
  "statusbar": {
    "priority": 45,
    "icon": "⚡",
    "items": [
      {"id": "cpu", "type": "live_status", "label": "CPU: {cpu_percent}%  Mem: {mem_percent}%", "refresh_seconds": 5}
    ]
  }
}
```

**Rendered** (inline, no actions):
```
⚡ CPU: 34%  Mem: 67%
```

### Disk Usage

**Manifest**:
```json
{
  "name": "disk-usage",
  "statusbar": {
    "priority": 80,
    "icon": "💾",
    "items": [
      {"id": "usage", "type": "live_status", "label": "Disk: {used} / {total} ({percent}%)", "refresh_seconds": 30}
    ]
  }
}
```

**Rendered** (inline):
```
💾 Disk: 234 GB / 500 GB (47%)
```

## Discovery Flow

When the status bar starts polling, it discovers plugins:

```
1. GET /api/plugins
   → [{id: "network-monitor", manifest: {..., statusbar: {...}}, ...}, ...]

2. For each plugin with a `statusbar` key in manifest:
   a. Parse the statusbar config (items, actions, submenu)
   b. Create NSMenuItems for each declared item
   c. Insert into the Plugins section in priority order

3. Every poll cycle (3s):
   a. GET /api/statusbar/state → includes plugin_data for all plugins
   b. For each plugin, extract statusbar dict
   c. Interpolate templates, update toggle states
   d. Refresh menu item titles
```

## Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Plugin has no `statusbar` key | Not shown in menu. Silent. |
| Plugin has `statusbar` but no `get_status()` | Items shown with `--` for all placeholders. |
| Plugin's `get_status()` raises | Items shown as "Error" in dim text. |
| Server returns 500 for plugin status | Items grayed out with last known values. |
| Template references nonexistent key | That placeholder renders as `--`. Other placeholders still work. |
| Action endpoint returns error | Show brief NSAlert with error message. |
| Plugin loaded after status bar started | Next poll discovers it, items appear. |
| Plugin unloaded while status bar running | Items disappear on next poll. |
