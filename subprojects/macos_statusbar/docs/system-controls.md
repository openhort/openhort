# System Controls

## Overview

The status bar manages several macOS system-level features that make openhort work reliably as a background service: sleep prevention, auto-start on login, permission management, and settings persistence.

These controls live in the Settings submenu and operate independently of the openhort server — they are local to the status bar process.

## Sleep Prevention

### The Problem

macOS aggressively sleeps when idle. If the Mac sleeps:
- The openhort server stops responding
- Active WebSocket connections drop
- Remote viewers see nothing
- Screen capture returns nothing (the display is off)

For a remote viewing tool, sleep is the primary reliability enemy.

### Implementation: IOPMAssertion

macOS provides `IOPMAssertionCreateWithName` — the official API for preventing sleep. This is the same mechanism used by Amphetamine, Caffeine, KeepingYouAwake, and similar utilities.

Two independent assertion types:

| Assertion | Constant | Effect |
|-----------|----------|--------|
| System sleep | `PreventUserIdleSystemSleep` | Mac stays awake even when idle. Display can still dim or turn off. |
| Display sleep | `PreventUserIdleDisplaySleep` | Display stays on. Implies system sleep prevention. |

### State Machine

```
                          ┌─────────────┐
                          │  No asserts  │  (sleep allowed)
                          └──────┬──────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
              ▼                  ▼                   ▼
    ┌──────────────┐   ┌───────────────┐   ┌──────────────────┐
    │ System only  │   │ Display only  │   │ System + Display │
    │ (default ON) │   │ (rare)        │   │ (auto when       │
    └──────────────┘   └───────────────┘   │  viewers present)│
                                           └──────────────────┘
```

### Automatic Display Sleep Management

The status bar automatically manages display sleep based on viewer state:

| Condition | System sleep | Display sleep |
|-----------|-------------|---------------|
| Server stopped, no viewers | User setting | User setting |
| Server running, no viewers | Prevented (if setting ON) | User setting |
| Server running, viewers connected | **Always prevented** | **Always prevented** |
| Server running, viewers disconnect | Prevented (if setting ON) | Reverts to user setting |

The key behavior: **display sleep is always prevented while viewers are connected**, regardless of the user's "Keep Display On" setting. This is because screen capture requires the display to be on. A viewer connecting to a sleeping display sees a black screen.

When viewers disconnect, display sleep reverts to the user's configured preference.

### Assertion Lifecycle

```python
# On server start (or status bar launch with server already running):
if settings.prevent_system_sleep:
    power.prevent_sleep(prevent_display_sleep=False)

# On viewer connect (observer_count 0 → N):
power.prevent_sleep(prevent_display_sleep=True)  # force display on

# On viewer disconnect (observer_count N → 0):
if settings.prevent_display_sleep:
    power.prevent_sleep(prevent_display_sleep=True)
elif settings.prevent_system_sleep:
    power.prevent_sleep(prevent_display_sleep=False)
else:
    power.allow_sleep()

# On server stop:
power.allow_sleep()  # release everything

# On quit:
power.allow_sleep()  # always clean up
```

### Clamshell Mode Limitation

On a MacBook with no external display, closing the lid forces system sleep regardless of IOPMAssertions. This is a macOS kernel-level behavior that cannot be overridden without a kernel extension (which Apple no longer allows on Apple Silicon).

**Workaround for users**: Connect an external display (even a dummy HDMI plug works). With an external display detected, the MacBook stays awake with the lid closed.

The status bar should document this in the Settings tooltip: "Note: MacBook lid close forces sleep unless an external display is connected."

### Menu Representation

```
Settings ▸
  ✓ Prevent Sleep                          ← toggles PreventUserIdleSystemSleep
    Keep Display On (auto while viewing)   ← toggles PreventUserIdleDisplaySleep
```

The "(auto while viewing)" suffix is a hint that display sleep is managed dynamically. Even if the user has "Keep Display On" unchecked, the display stays on while viewers are connected.

## Auto-Start on Login

### LaunchAgent Mechanism

macOS uses LaunchAgents for per-user auto-start services. A plist file in `~/Library/LaunchAgents/` tells `launchd` to start a process at login.

### Plist File

Location: `~/Library/LaunchAgents/com.openhort.statusbar.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openhort.statusbar</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/michael/.pyenv/versions/3.12.7/bin/python</string>
        <string>-m</string>
        <string>hort_statusbar</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <false/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/tmp/hort-statusbar.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/hort-statusbar.log</string>
</dict>
</plist>
```

### Key Decisions

**`KeepAlive: false`**: The status bar should NOT auto-restart if it crashes or is quit. If the user quits, it stays quit. If it crashes, the user should investigate, not have it silently restart in a potentially broken state.

**`RunAtLoad: true`**: Start at login, not on demand.

**`ProgramArguments`**: Uses the full path to the Python interpreter that was active when the user enabled autostart. This handles pyenv, poetry, conda, and system Python correctly. If the user changes their Python version, they need to re-enable autostart (the plist points to the old interpreter).

**`StandardOutPath`**: Logs to `/tmp/hort-statusbar.log` for debugging launch issues. This file is in `/tmp/` which macOS cleans on reboot, so it doesn't accumulate.

### Install / Uninstall

```python
def install_launch_agent():
    """Write plist and load it."""
    content = PLIST_TEMPLATE.format(
        python=sys.executable,
        path=os.environ.get("PATH", "..."),
    )
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(content)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=False)

def uninstall_launch_agent():
    """Unload and delete plist."""
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
    PLIST_PATH.unlink(missing_ok=True)
```

### Two Independent Auto-Start Settings

| Setting | What it does | Default |
|---------|-------------|---------|
| **Start on Login** | Launches the status bar app at login (LaunchAgent) | OFF |
| **Auto-start Server** | Status bar starts the openhort server automatically when it launches | OFF |

These are independent. Common configurations:

| Start on Login | Auto-start Server | Result |
|---------------|-------------------|--------|
| OFF | OFF | Manual everything — user starts status bar and server separately |
| ON | OFF | Status bar appears at login, shows "Server: Stopped". User starts server from menu when needed. |
| ON | ON | Full auto — login starts status bar, which starts server. openhort is always available. |
| OFF | ON | Unusual — if someone manually starts the status bar, it auto-starts the server. |

### Menu Representation

```
Settings ▸
  ...
    Start on Login                    ← toggle: install/remove LaunchAgent
    Auto-start Server                 ← toggle: server starts when status bar launches
```

## Permission Management

### Required Permissions

openhort needs two macOS permissions:

| Permission | What it enables | Impact if missing |
|-----------|----------------|-------------------|
| **Screen Recording** | `CGWindowListCreateImage`, `CGDisplayCreateImage` | Captures return blank/transparent images. Server runs but viewers see nothing. |
| **Accessibility** | `CGEventPost` (input simulation), AX API (window info) | Mouse/keyboard forwarding doesn't work. Viewing works, controlling doesn't. |

### Detection

```python
import Quartz
import ApplicationServices

screen_recording = Quartz.CGPreflightScreenCaptureAccess()      # bool
accessibility = ApplicationServices.AXIsProcessTrusted()          # bool
```

These are instant checks (no I/O, no dialog). Safe to call frequently.

### Requesting Permissions

**Screen Recording**: `Quartz.CGRequestScreenCaptureAccess()` — triggers the macOS permission dialog. The user must grant access and restart the app (macOS requirement — the permission doesn't take effect until the process restarts).

**Accessibility**: `ApplicationServices.AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})` — opens System Settings > Privacy > Accessibility with our process highlighted.

### Permission Flow

```
Status bar launches
  │
  ├─ Check permissions
  │   ├─ Screen Recording: ✓    → OK
  │   ├─ Screen Recording: ✗    → Show warning in menu
  │   ├─ Accessibility: ✓       → OK
  │   └─ Accessibility: ✗       → Show warning in menu
  │
  └─ If any missing:
      ├─ Icon state: ATTENTION (yellow dot)
      ├─ Permission warning section visible in menu
      └─ Re-check every 30 seconds
          │
          └─ When all granted:
              ├─ Warning section hides
              ├─ Icon state: based on server (green/red/gray)
              └─ Check frequency drops to 60s
```

### First-Launch Experience

On the very first launch, the status bar should proactively request permissions:

1. Show an alert: "openhort needs Screen Recording and Accessibility permissions to work."
2. Call `CGRequestScreenCaptureAccess()` — macOS shows its permission dialog
3. If denied, show the menu bar warning. User can re-request from Settings > Check Permissions.
4. Call `AXIsProcessTrustedWithOptions` — opens System Settings

This only happens once (tracked by a `first_launch_done` flag in settings).

### App vs Process Permission

macOS grants permissions to specific apps (by bundle ID or code signature). When running from `python -m hort_statusbar`, the permission is granted to the Python interpreter, not to openhort specifically. This means:
- All Python scripts run from the same interpreter share the permission
- If the user has multiple Python versions, each one needs its own permission grant
- A py2app-bundled `.app` would have its own bundle ID and its own permission entry

The status bar should detect which process holds the permission and show the correct name in the warning: "Grant Screen Recording access to Python 3.12 in System Settings."

## Settings Persistence

### Storage Location

```
~/Library/Application Support/openhort/statusbar.json
```

This follows macOS convention for per-user application data. The directory is created on first write.

### Schema

```json
{
  "version": 1,
  "power": {
    "prevent_system_sleep": true,
    "prevent_display_sleep": false
  },
  "overlay": {
    "enabled": true,
    "position": "top-center"
  },
  "autostart": {
    "auto_start_server": false
  },
  "notifications": {
    "on_first_viewer": true,
    "on_server_error": true
  },
  "first_launch_done": true
}
```

Note: "Start on Login" is NOT stored in this file. It's determined by whether the LaunchAgent plist exists. This avoids state drift between the settings file and the actual LaunchAgent.

### Version Field

The `version` field enables future migrations. If the settings schema changes, the loader can detect the old version and migrate:

```python
def _load_settings(self) -> dict:
    if not SETTINGS_PATH.exists():
        return DEFAULT_SETTINGS
    data = json.loads(SETTINGS_PATH.read_text())
    if data.get("version", 0) < CURRENT_VERSION:
        data = _migrate(data)
        self._save_settings(data)
    return data
```

### Write Strategy

Settings are written atomically (write to temp file, then `os.replace`) to prevent corruption if the process is killed mid-write:

```python
def _save_settings(self, data: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_PATH))
```

### Default Values

Every setting has a hardcoded default. If the settings file is missing, corrupt, or has missing keys, defaults are used. The settings file is never required — the app works without it.

| Setting | Default | Rationale |
|---------|---------|-----------|
| `prevent_system_sleep` | `true` | The primary reason to run openhort is remote access. Sleeping defeats the purpose. |
| `prevent_display_sleep` | `false` | Display sleep saves power. Display auto-wakes when viewers connect. |
| `overlay.enabled` | `true` | Privacy-first: users should see the viewer warning by default. |
| `overlay.position` | `"top-center"` | Most visible, least intrusive. |
| `auto_start_server` | `false` | Don't start the server without explicit user intent. |
| `notifications.on_first_viewer` | `true` | Privacy-first: notify when someone starts watching. |
| `notifications.on_server_error` | `true` | Helps diagnose problems. |

## Server Lifecycle Management

### Start Server

The status bar manages the server as a subprocess:

```python
self._process = subprocess.Popen(
    [sys.executable, str(self._project_root / "run.py")],
    cwd=str(self._project_root),
    env={**os.environ, "LLMING_DEV": "0"},
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
```

**Stdout capture**: Server output is captured via `PIPE`. The status bar doesn't display it in real-time, but it's available for diagnostics (the "Show Debug Info" action in Settings can show the last N lines).

**Working directory**: Set to the project root so that relative paths in the server code (static files, certs, logs) resolve correctly.

**Environment**: `LLMING_DEV=0` forces production mode (no `--reload`). The server runs as a single stable process.

### Detect External Server

Before starting a subprocess, the status bar checks if port 8940 is already in use:

```python
def _is_port_in_use(self) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", 8940)) == 0
```

If the port is in use, the status bar **attaches** to the existing server instead of spawning a new one. The menu shows "Server: Running" and all monitoring features work. "Stop Server" will kill the external process by name (`pgrep -f "uvicorn hort.app"`).

### Stop Server

**Own subprocess**: Send SIGTERM, wait 5 seconds, SIGKILL if needed.

**External process**: Find by name and send SIGTERM:
```python
pids = subprocess.check_output(["pgrep", "-f", "uvicorn hort.app"]).strip().split()
for pid in pids:
    os.kill(int(pid), signal.SIGTERM)
```

**NEVER** use `lsof -ti :8940 | xargs kill` — this kills Docker containers connected to the port.

### Restart Server

"Restart" is not a separate action — it's "Stop" followed by "Start" with a 3-second delay:

```python
async def restart_server(self):
    self.stop_server()
    await asyncio.sleep(3)  # wait for port to be released
    self.start_server()
```

The 3-second delay is necessary because:
1. SIGTERM triggers uvicorn's graceful shutdown
2. Open WebSocket connections need time to close
3. The OS needs time to release the port

If the port is still busy after 3 seconds, the start attempt detects this via `_is_port_in_use()` and shows "Port still in use — please wait".

### Crash Detection

The background polling loop checks if the subprocess is still alive:

```python
if self._process and self._process.poll() is not None:
    exit_code = self._process.returncode
    self._status.error = f"Server crashed (exit code {exit_code})"
```

On crash:
- Icon changes to ATTENTION (yellow)
- Menu shows "Server: Crashed (exit 1)"
- A notification is posted (if enabled)
- "Start Server" button is re-enabled for manual restart
- The server is NOT automatically restarted (the crash might be due to a config error; auto-restart would loop)
