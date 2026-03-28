# Menu Structure

## Overview

The menu is an `NSMenu` attached to the `NSStatusItem`. It is rebuilt dynamically on every poll cycle (every 3 seconds) to reflect live server state. The menu is organized into seven fixed sections separated by `NSMenuItem.separatorItem()`. Plugin-contributed items are inserted into the Plugins section.

```
┌──────────────────────────────────────────────────┐
│  § Status Header                                 │
├──────────────────────────────────────────────────┤
│  § Permission Warning  (conditional)             │
├──────────────────────────────────────────────────┤
│  § Server Controls                               │
├──────────────────────────────────────────────────┤
│  § Connected Viewers   (submenu)                 │
├──────────────────────────────────────────────────┤
│  § Targets             (submenu)                 │
├──────────────────────────────────────────────────┤
│  § Plugins             (dynamic, from manifests) │
├──────────────────────────────────────────────────┤
│  § Settings            (submenu)                 │
├──────────────────────────────────────────────────┤
│  Quit openhort                                   │
└──────────────────────────────────────────────────┘
```

## Section 1: Status Header

Always visible. Three non-clickable (disabled) lines showing the current state at a glance.

```
  Server: Running                           v0.1.0
  ● 2 viewers connected
  LAN: 192.168.1.42:8950
```

### Items

| Item | Text when server running | Text when server stopped | Text when error |
|------|-------------------------|------------------------|-----------------|
| Server status | `Server: Running` | `Server: Stopped` | `Server: Not Responding` or `Server: Crashed (exit 1)` |
| Viewer count | `● N viewer(s) connected` (red ●) | `No active viewers` | — (hidden) |
| Network address | `LAN: 192.168.1.42:8950` | — (hidden) | — (hidden) |
| Version | `v0.1.0` (right-aligned on status line) | — (hidden) | — (hidden) |

### Viewer Count Emphasis

The viewer line is the most important item in the entire menu. When `observer_count > 0`:
- Prefix with a red bullet `●` (Unicode U+25CF)
- Use `NSAttributedString` to render the text in bold with a red `●` prefix
- If macOS doesn't support attributed strings in menu items gracefully, fall back to plain text with the `●` character

When `observer_count == 0`, show "No active viewers" in dim text — standard disabled NSMenuItem.

### Data Sources

| Field | Source | Fallback |
|-------|--------|----------|
| Server status | Process check + `GET /api/hash` response | "Stopped" if connection refused |
| Observer count | `GET /api/statusbar/state` → `.viewers` count | WS `get_status` → `.observers` |
| LAN IP | `GET /api/statusbar/state` → `.server.lan_ip` | `GET /api/connectors` → `.lan` |
| Version | `GET /api/statusbar/state` → `.server.version` | WS `get_status` → `.version` |

### Edge Cases

- **Server starting**: Show "Server: Starting…" with an ellipsis animation (cycle between 1-3 dots every second) while the process is alive but `/api/hash` hasn't responded yet.
- **Server address changes**: If the Mac's LAN IP changes (Wi-Fi → Ethernet, VPN connects), the address line updates on next poll.
- **Multiple interfaces**: Show the primary LAN IP only. If the server is listening on 0.0.0.0, show the IP that `get_lan_ip()` returns.

## Section 2: Permission Warning

**Conditional** — only appears when one or more macOS permissions are missing. Disappears once all permissions are granted.

```
  ⚠ Screen Recording permission needed
```

or, if multiple are missing:

```
  ⚠ Permissions needed: Screen Recording, Accessibility
```

### Behavior

- Clicking the item opens the relevant System Settings pane
- If Screen Recording is missing: opens `x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture`
- If Accessibility is missing: calls `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})`
- If both are missing: clicking opens Screen Recording first (more critical for core functionality)

### Why This Matters

Without Screen Recording, `CGWindowListCreateImage` returns blank images. The server runs, viewers connect, but they see nothing. This is confusing and hard to diagnose. The permission warning makes the problem obvious and one-click-fixable.

Without Accessibility, input simulation (mouse/keyboard forwarding) doesn't work. Viewing works, controlling doesn't.

### Check Frequency

Permissions are checked:
1. Once on status bar app launch
2. Every 30 seconds while the warning is shown (more frequently than the 3s poll — permissions can be granted at any time)
3. After the user clicks the warning item (they likely went to System Settings to grant it)

Once both permissions are granted, the warning section disappears and permission checks drop to every 60 seconds (background verification).

## Section 3: Server Controls

Four action items for managing the server.

```
  Start Server          (or "Stop Server" when running)
  Open in Browser…
  Copy URL
  Show QR Code…
```

### Start / Stop Server

A single toggle item. Label and behavior change based on server state:

| Server state | Label | Action |
|-------------|-------|--------|
| Stopped | Start Server | Spawn `python run.py` subprocess |
| Running (own subprocess) | Stop Server | Send SIGTERM to subprocess, wait 5s, SIGKILL if needed |
| Running (external) | Stop Server | `pgrep -f "uvicorn hort.app"` → SIGTERM |
| Starting | Starting… | Disabled (grayed out) |

**Start behavior in detail:**
1. Check if port 8940 is in use → if yes, attach to existing server (don't spawn)
2. Find `run.py` relative to project root
3. Spawn `subprocess.Popen([sys.executable, run.py], cwd=project_root)`
4. Set menu to "Starting…" (disabled)
5. Poll `/api/hash` every 500ms until it responds (max 30 seconds)
6. Once responding → update to "Stop Server"
7. If timeout → show "Server: Failed to Start" + enable "Start Server" again

**Stop behavior in detail:**
1. If we own the subprocess: `process.send_signal(SIGTERM)`, wait 5s, SIGKILL if needed
2. If external: `pgrep -f "uvicorn hort.app"` → SIGTERM each PID
3. NEVER use `lsof -ti :8940 | xargs kill` — this kills Docker containers
4. Set menu to "Server: Stopped" immediately
5. Verify port is free within 5 seconds

### Open in Browser…

Opens the default browser with the server URL. Enabled only when server is running.

Priority for URL selection:
1. HTTPS LAN URL (`https://192.168.1.42:8950`) — preferred, works on same network
2. HTTP localhost (`http://localhost:8940`) — fallback if LAN IP unknown

The trailing `…` (ellipsis) in the label follows macOS convention: the action opens something outside the menu.

### Copy URL

Copies the HTTPS LAN URL to the system pasteboard. Shows a brief checkmark feedback:

```
  Copy URL  →  (click)  →  ✓ Copied!  →  (1.5s later)  →  Copy URL
```

Implementation: after copying, change the item title to "✓ Copied!" for 1.5 seconds, then revert. Use `NSTimer.scheduledTimerWithTimeInterval_` on the main thread.

### Show QR Code…

Opens a small borderless floating window (300x300) showing the QR code for the server URL. The QR is fetched from `GET /api/qr?url={https_url}` and rendered as an NSImage.

The window:
- Borderless, with rounded corners and a shadow
- Positioned near the menu bar icon
- Click-anywhere-to-dismiss (registers a global click handler)
- Shows the URL as text below the QR code

## Section 4: Connected Viewers

A submenu listing every active viewer session with detail.

```
  Connected Viewers (2) ▸
    ┌────────────────────────────────────────────┐
    │  👁 iPhone (Safari)                        │
    │     Viewing: Desktop          00:12:34     │
    │  👁 iPad (Chrome)                          │
    │     Viewing: Terminal (zsh)   00:03:21     │
    │  ─────────────────────────────             │
    │  Disconnect All                            │
    └────────────────────────────────────────────┘
```

### Per-Viewer Items

Each viewer gets two lines (a header and a detail line):

**Header**: Device + browser extracted from User-Agent. Examples:
- `iPhone (Safari)` — mobile Safari
- `iPad (Chrome)` — Chrome on iPad
- `Mac (Firefox)` — desktop Firefox
- `Unknown device` — unrecognized UA

**Detail**: What they're viewing + connection duration:
- `Viewing: Desktop` — streaming the full desktop (window_id = -1)
- `Viewing: iTerm2 — ~/projects` — streaming a specific window (owner_name + window_name)
- `Viewing: Terminal (bash)` — in a terminal session
- `Connected` — session exists but not streaming (just browsing the window grid)

Duration formatted as `HH:MM:SS`, calculated from `connected_at` timestamp.

### Disconnect All

Sends a request to close all active stream WebSockets:

```
POST /api/sessions/disconnect-all
```

This is the panic button. One click, all viewers gone. The server stays running — new viewers can connect, but existing streams are cut.

A confirmation alert is NOT shown for this action — speed matters. If someone is watching your screen and you want them gone, you don't want to click through a dialog.

### No Viewers

When no viewers are connected, the submenu shows a single disabled item:

```
  Connected Viewers ▸
    ┌─────────────────────┐
    │  No active viewers  │
    └─────────────────────┘
```

### Data Source

Requires `GET /api/sessions/active` (new endpoint, see [Server API](server-api.md)).

## Section 5: Targets

A submenu listing registered platform targets.

```
  Targets ▸
    ┌───────────────────────────────────────────┐
    │  ✓ This Mac                    available  │
    │    Linux (openhort-linux-desktop)  available  │
    │    Azure VM (dev-sandbox)      connecting  │
    └───────────────────────────────────────────┘
```

### Behavior

- Each target shows its name and status
- The active/default target has a checkmark
- Clicking a target opens the browser viewer pre-filtered to that target: `open "http://localhost:8940/viewer?target={target_id}"`
- Target status shown in dim text: `available`, `connecting`, `error`, `offline`

### Data Source

`GET /api/statusbar/state` → `.targets` array, or `GET /api/targets` standalone.

### Empty State

When only the local macOS target exists (typical single-machine setup):

```
  Targets ▸
    ┌──────────────────────────┐
    │  ✓ This Mac   available  │
    └──────────────────────────┘
```

Only showing one target is still useful — it confirms the local platform provider loaded successfully.

## Section 6: Plugins

Dynamic section populated from plugin manifests that declare a `statusbar` key. See [Plugin Contributions](plugin-contributions.md) for the full specification.

```
  ─── Plugins ───                              ← section header (disabled)
  📡 Telegram Bot: Running                     ← live_status item
  🌐 Network: ↑ 2.3 MB/s  ↓ 450 KB/s         ← live_status item
  🔗 P2P Tunnel: 1 active                     ← live_status item
  📋 Clipboard: 12 items                      ← live_status item
```

### Ordering

Plugins appear in the order they are loaded by the plugin registry. If a plugin declares `statusbar.priority` (integer), lower numbers appear first. Default priority is 100.

### Section Header

The "─── Plugins ───" header is a disabled NSMenuItem with an attributed string (dim, centered dashes). It only appears if at least one plugin has statusbar contributions. If no plugins contribute, the entire section (header + separator) is omitted.

### Empty / Server Stopped

When the server is stopped, plugin data is unavailable. The section shows:

```
  ─── Plugins ───
  Plugin status unavailable (server stopped)
```

## Section 7: Settings

A submenu with checkmark toggles and utility actions.

```
  Settings ▸
    ┌──────────────────────────────────────┐
    │  ✓ Prevent Sleep                     │
    │    Keep Display On                   │
    │  ✓ Show Viewer Warning               │
    │  ─────────────────────               │
    │    Start on Login                    │
    │    Auto-start Server                 │
    │  ─────────────────────               │
    │    Check Permissions…                │
    │    Open Logs…                        │
    │    Show Debug Info                   │
    │  ─────────────────────               │
    │    Reset Settings                    │
    └──────────────────────────────────────┘
```

### Toggle Items

| Item | Default | Persisted | Effect |
|------|---------|-----------|--------|
| Prevent Sleep | ON | Yes | IOPMAssertion `PreventUserIdleSystemSleep` |
| Keep Display On | OFF | Yes | IOPMAssertion `PreventUserIdleDisplaySleep` |
| Show Viewer Warning | ON | Yes | Floating overlay banner visibility |
| Start on Login | OFF | Via LaunchAgent | Install/remove `com.openhort.statusbar.plist` |
| Auto-start Server | OFF | Yes | Start server automatically when status bar launches |

All toggle items show a checkmark (`NSControlStateValueOn`) when enabled. Clicking toggles the state immediately and persists to `statusbar.json`.

### Utility Actions

| Item | Action |
|------|--------|
| Check Permissions… | Opens System Settings to relevant Privacy pane |
| Open Logs… | `open` the `logs/openhort.log` file in Console.app or default text editor |
| Show Debug Info | Toggles showing `GET /api/debug/memory` output as an alert (RSS, tasks, etc.) |
| Reset Settings | Deletes `statusbar.json`, resets all toggles to defaults, asks for confirmation first |

## Menu Update Strategy

The menu is **not rebuilt from scratch** on every poll. Instead, individual items are updated in place:

```python
def _update_menu(self, state: StatusBarState) -> None:
    # Update text of existing items
    self._server_status_item.setTitle_(f"Server: {state.server_status}")
    self._viewer_item.setTitle_(self._format_viewers(state.observers))

    # Show/hide conditional sections
    self._permission_item.setHidden_(state.permissions_ok)

    # Rebuild viewer submenu (small, cheap)
    self._rebuild_viewer_submenu(state.viewers)

    # Update plugin items
    self._update_plugin_items(state.plugin_data)
```

Rebuilding the entire NSMenu on every poll would cause visual flicker (menu closes and reopens if the user is browsing it). Updating items in place is flicker-free.

**Exception**: The viewer submenu and plugin section are rebuilt when the set of items changes (viewer connects/disconnects, plugin loads/unloads). This is done by removing old items and inserting new ones, which AppKit handles smoothly even while the menu is open.

## Keyboard Navigation

macOS menus support keyboard navigation natively. No additional work needed — arrow keys move between items, Enter/Space activates, Escape closes.

Optional enhancements:
- **Key equivalents** on frequently used items: `Cmd+S` for Start/Stop, `Cmd+O` for Open in Browser
- These only activate when the menu is open (not global shortcuts)
- Set via `NSMenuItem.setKeyEquivalent_` + `setKeyEquivalentModifierMask_`

## Menu Width

NSMenu auto-sizes to fit the widest item. To prevent excessively wide menus from long plugin text or window names:
- Viewer detail lines are truncated to 40 characters with `…`
- Plugin live status text is truncated to 50 characters
- LAN IP line is never truncated (short and important)
