# macOS Desktop App — Design Document

## Problem

Hort currently runs via `poetry run python run.py` from a terminal. This is fine for developers, but for a non-technical user:
- They don't know what a terminal is
- They can't tell if the server is running
- The Mac will sleep and kill the connection
- They have no idea someone is watching their screen remotely
- No way to start/stop without opening a terminal

We need a proper macOS app that feels like any other native utility — sits in the menu bar, starts on login, prevents sleep, and warns when someone connects.

## Goals

1. **Menu bar presence** — icon + dropdown with status, start/stop, settings — works from `pip install` too, no `.app` required
2. **Prevent sleep** — keep the Mac awake while hort is serving (even with lid closed on external monitor, or display off)
3. **Remote viewing indicator** — visible warning when someone is actively viewing a window
4. **pip/poetry-first distribution** — install via `pip install hort`, users can install plugins into the same environment
5. **Optional `.app` bundle** — for non-techies who don't want a terminal; wraps the same code
6. **Auto-start on login** — optional, via LaunchAgent

## Distribution Strategy: pip-first, .app optional

```
                        pip install hort
                              │
                    ┌─────────┴──────────┐
                    │                    │
              hort --headless       hort (default)
              (server only,         (server + menu bar)
               no GUI, works        needs macOS + PyObjC
               on Linux too)
                                         │
                                    optional packaging
                                         │
                                    py2app → Hort.app
                                    (for non-techies)
```

**Why pip-first:**
- Users can `pip install` plugins into the same environment
- Plugin authors need the Python environment accessible
- No license bundling headaches — pip deps are installed, not redistributed
- The `.app` bundle is just a wrapper around the same `hort` command

**The menu bar works from pip install.** `NSStatusBar` doesn't require a `.app` bundle — any Python process can create a status item. `rumps` (a pip package) proves this. The only requirement is that the macOS AppKit run loop runs on the main thread.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              hort process (pip-installed)                 │
│                                                          │
│  Main thread                Background thread            │
│  ┌──────────────────┐      ┌──────────────────────────┐  │
│  │  AppKit Run Loop  │      │  asyncio Event Loop       │  │
│  │                   │      │                            │  │
│  │  Menu Bar Agent   │←────→│  FastAPI Server            │  │
│  │  • Status icon    │      │  • HTTP :8940              │  │
│  │  • Start / Stop   │      │  • WS control + stream     │  │
│  │  • Connection cnt │      │  • Terminal sessions        │  │
│  │  • Settings       │      │  • Extension system         │  │
│  │                   │      │  • Plugin loading           │  │
│  │  Viewer Overlay   │      └──────────────────────────┘  │
│  │  • Red banner     │                                    │
│  │  • Viewer count   │      ┌──────────────────────────┐  │
│  │                   │      │  Power Manager             │  │
│  │  Quit Handler     │      │  (IOPMAssertion)           │  │
│  └──────────────────┘      └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

Communication:
  main→bg: loop.call_soon_threadsafe()
  bg→main: NSOperationQueue.mainQueue().addOperationWithBlock_()
```

**Headless mode** (`hort --headless`): skips the AppKit run loop, runs asyncio on the main thread — same as today. Works on Linux, in Docker, in SSH sessions, etc.

### Why Not `rumps`?

`rumps` (Ridiculously Uncomplicated macOS Python Statusbar apps) is the obvious choice — 50 lines for a menu bar app. But:
- It wraps `NSStatusBar` with a simplified API that hides too much
- We need dynamic menu updates (viewer count, connection status)
- We need to create `NSWindow` overlays for the viewer warning
- We already have PyObjC as a dependency
- `rumps` adds another dependency for something we can do in ~150 lines of PyObjC

**Decision:** Direct PyObjC (`AppKit.NSStatusBar`, `AppKit.NSApplication`). We already depend on `pyobjc-framework-Quartz`; adding `pyobjc-framework-Cocoa` is trivial.

## Component Design

### 1. Menu Bar Agent

The NSStatusItem lives in the macOS menu bar (top-right area). It shows an icon and a dropdown menu.

```python
# hort/desktop/menubar.py

import AppKit
import objc

class HortMenuBarAgent:
    """Menu bar status item with server controls."""

    def __init__(self, server_controller):
        self._server = server_controller
        self._status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        self._setup_icon()
        self._build_menu()

    def _setup_icon(self):
        # SF Symbol or bundled PNG — small monochrome icon
        # Green dot overlay when running, gray when stopped
        button = self._status_item.button()
        button.setImage_(self._load_icon("hort-menubar"))
        button.setToolTip_("Hort — Remote Window Viewer")

    def _build_menu(self):
        menu = AppKit.NSMenu.alloc().init()

        # Status line (non-clickable)
        self._status_item_menu = self._add_item(menu, "Server: Stopped", None)
        self._status_item_menu.setEnabled_(False)

        self._viewers_item = self._add_item(menu, "No active viewers", None)
        self._viewers_item.setEnabled_(False)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Controls
        self._start_stop = self._add_item(menu, "Start Server", "toggleServer:")
        self._add_item(menu, "Open in Browser...", "openBrowser:")
        self._add_item(menu, "Copy URL", "copyURL:")

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Settings submenu
        settings = AppKit.NSMenu.alloc().init()
        self._sleep_item = self._add_item(settings, "Prevent Sleep", "toggleSleep:")
        self._sleep_item.setState_(AppKit.NSControlStateValueOn)  # on by default
        self._autostart_item = self._add_item(settings, "Start on Login", "toggleAutostart:")
        self._overlay_item = self._add_item(settings, "Show Viewer Warning", "toggleOverlay:")
        self._overlay_item.setState_(AppKit.NSControlStateValueOn)

        settings_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings", None, ""
        )
        settings_item.setSubmenu_(settings)
        menu.addItem_(settings_item)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add_item(menu, "Quit Hort", "quit:")

        self._status_item.setMenu_(menu)

    def update_status(self, running: bool, viewer_count: int):
        """Called from server thread to update menu bar state."""
        # Must dispatch to main thread for AppKit
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: self._do_update(running, viewer_count)
        )

    def _do_update(self, running, viewer_count):
        if running:
            self._status_item_menu.setTitle_("Server: Running")
            self._start_stop.setTitle_("Stop Server")
            button = self._status_item.button()
            button.setImage_(self._load_icon("hort-menubar-active"))
        else:
            self._status_item_menu.setTitle_("Server: Stopped")
            self._start_stop.setTitle_("Start Server")
            button = self._status_item.button()
            button.setImage_(self._load_icon("hort-menubar"))

        if viewer_count > 0:
            self._viewers_item.setTitle_(f"{viewer_count} viewer{'s' if viewer_count != 1 else ''} connected")
        else:
            self._viewers_item.setTitle_("No active viewers")
```

#### Menu Structure

```
[H] Hort                          ← menu bar icon (monochrome)
─────────────────────────────
  Server: Running                  ← status (grayed, non-clickable)
  2 viewers connected              ← viewer count (grayed)
─────────────────────────────
  Start Server / Stop Server       ← toggle
  Open in Browser...               ← opens http://localhost:8940
  Copy URL                         ← copies LAN URL to clipboard
─────────────────────────────
  Settings ▸
    ✓ Prevent Sleep                ← IOPMAssertion toggle
    ✓ Start on Login               ← LaunchAgent toggle
    ✓ Show Viewer Warning          ← overlay toggle
─────────────────────────────
  Quit Hort
```

### 2. Power Management (Sleep Prevention)

macOS has a proper API for this: `IOPMAssertionCreateWithName`. This is what Amphetamine, Caffeine, and similar apps use.

```python
# hort/desktop/power.py

import ctypes
import ctypes.util

IOKit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("IOKit"))

kIOPMAssertionTypePreventUserIdleSystemSleep = "PreventUserIdleSystemSleep"
kIOPMAssertionTypePreventUserIdleDisplaySleep = "PreventUserIdleDisplaySleep"

class PowerManager:
    """Prevents macOS from sleeping while hort is serving."""

    def __init__(self):
        self._system_assertion_id = ctypes.c_uint32(0)
        self._display_assertion_id = ctypes.c_uint32(0)
        self._active = False

    def prevent_sleep(self, prevent_display_sleep: bool = False):
        """Create IOPMAssertion to prevent system sleep.

        Args:
            prevent_display_sleep: If True, also prevents the display from
                turning off. If False, only prevents system sleep (display
                can still dim/off, but machine stays awake).
        """
        if self._active:
            return

        reason = ctypes.c_void_p(
            AppKit.NSString.stringWithString_("Hort remote viewer is active")
        )

        # Always prevent system sleep
        IOKit.IOPMAssertionCreateWithName(
            ctypes.c_void_p(AppKit.NSString.stringWithString_(
                kIOPMAssertionTypePreventUserIdleSystemSleep
            )),
            255,  # kIOPMAssertionLevelOn
            reason,
            ctypes.byref(self._system_assertion_id),
        )

        if prevent_display_sleep:
            IOKit.IOPMAssertionCreateWithName(
                ctypes.c_void_p(AppKit.NSString.stringWithString_(
                    kIOPMAssertionTypePreventUserIdleDisplaySleep
                )),
                255,
                reason,
                ctypes.byref(self._display_assertion_id),
            )

        self._active = True

    def allow_sleep(self):
        """Release assertions, allow sleep again."""
        if not self._active:
            return

        if self._system_assertion_id.value:
            IOKit.IOPMAssertionRelease(self._system_assertion_id)
            self._system_assertion_id = ctypes.c_uint32(0)

        if self._display_assertion_id.value:
            IOKit.IOPMAssertionRelease(self._display_assertion_id)
            self._display_assertion_id = ctypes.c_uint32(0)

        self._active = False

    @property
    def is_preventing_sleep(self) -> bool:
        return self._active
```

**Two levels of prevention:**

| Setting | System Sleep | Display Sleep | Use Case |
|---|---|---|---|
| `PreventUserIdleSystemSleep` | Prevented | Allowed (dims/off) | Default — Mac stays awake, screen saves power |
| `PreventUserIdleDisplaySleep` | Prevented | Prevented | When user wants screen always on |

**Default:** Prevent system sleep only. The display can turn off (saves energy, less suspicious), but the Mac stays awake and hort keeps serving. User can toggle display sleep prevention in Settings.

**Lid-closed behavior:** On a MacBook connected to an external display, preventing system sleep keeps it running with the lid closed. On a MacBook with no external display, Apple forces sleep on lid close (clamshell mode) — there is no clean way around this without kernel extensions. We should document this limitation.

### 3. Remote Viewing Indicator

When someone connects to view a window, the user at the physical machine should know. This is both a privacy feature and a security measure.

#### Approach: Floating Overlay Banner

A small, semi-transparent floating window at the top of the screen — similar to the macOS screen recording indicator, but more visible.

```python
# hort/desktop/overlay.py

import AppKit
import Foundation

class ViewerOverlay:
    """Floating banner showing active remote viewer count."""

    def __init__(self):
        self._window = None
        self._viewer_count = 0

    def show(self, viewer_count: int):
        """Show or update the overlay with current viewer count."""
        self._viewer_count = viewer_count

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: self._show_on_main(viewer_count)
        )

    def _show_on_main(self, count):
        if self._window is None:
            self._create_window()

        self._label.setStringValue_(
            f"Remote viewing active — {count} viewer{'s' if count != 1 else ''}"
        )
        self._window.orderFront_(None)

    def _create_window(self):
        # Position: top-center of main screen, below menu bar
        screen = AppKit.NSScreen.mainScreen().frame()
        width, height = 320, 32
        x = (screen.size.width - width) / 2
        y = screen.size.height - 45  # just below menu bar

        rect = Foundation.NSMakeRect(x, y, width, height)

        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )

        # Floating, always-on-top, transparent, ignores mouse
        self._window.setLevel_(AppKit.NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(0.9, 0.2, 0.2, 0.85)
        )
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(True)  # click-through
        self._window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces  # visible on all Spaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        # Round corners
        self._window.contentView().setWantsLayer_(True)
        self._window.contentView().layer().setCornerRadius_(8)
        self._window.contentView().layer().setMasksToBounds_(True)

        # Label
        self._label = AppKit.NSTextField.labelWithString_("")
        self._label.setFrame_(Foundation.NSMakeRect(0, 0, width, height))
        self._label.setAlignment_(AppKit.NSTextAlignmentCenter)
        self._label.setTextColor_(AppKit.NSColor.whiteColor())
        self._label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(13, AppKit.NSFontWeightMedium))
        self._label.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._label.setBezeled_(False)
        self._label.setEditable_(False)

        self._window.contentView().addSubview_(self._label)

    def hide(self):
        """Hide the overlay when no viewers are connected."""
        if self._window:
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: self._window.orderOut_(None)
            )
```

#### Visual Design

```
┌──────────────────────────────────────────────────┐
│  ● Remote viewing active — 2 viewers             │  ← red banner, white text
└──────────────────────────────────────────────────┘
   ↑ Floating, always-on-top, click-through, rounded corners
   ↑ Appears on all Spaces
   ↑ Positioned just below the menu bar, centered
```

**Behavior:**
- Appears when first remote viewer connects to any stream WebSocket
- Updates count as viewers join/leave
- Disappears when last viewer disconnects
- Click-through — doesn't interfere with using the Mac normally
- Visible on all Spaces (not just the one where hort was started)
- Optional: configurable position (top-center, top-right), can be disabled in Settings

#### Hook into Existing Stream Code

The overlay integrates with `hort/stream.py` where binary WebSocket connections are tracked:

```python
# In hort/stream.py or hort/controller.py — pseudocode for the integration point

# When a viewer connects to the stream WebSocket:
active_viewers += 1
if desktop_app:
    desktop_app.overlay.show(active_viewers)

# When a viewer disconnects:
active_viewers -= 1
if active_viewers == 0:
    desktop_app.overlay.hide()
else:
    desktop_app.overlay.show(active_viewers)
```

### 4. App Lifecycle & Server Integration

The critical design question: how does the NSApplication run loop coexist with the asyncio event loop?

**Answer:** AppKit owns the main thread, asyncio runs on a background thread. This is the same model whether launched from `pip install` or from a `.app` bundle — the code is identical.

```python
# hort/desktop/app.py

import threading
import asyncio
import AppKit

class HortDesktopApp:
    """Desktop integration — status bar icon, sleep prevention, viewer overlay.

    Works from both `hort` (pip-installed CLI) and `Hort.app` (py2app bundle).
    The code is identical — the only difference is how the process was launched.
    """

    def __init__(self):
        self.power = PowerManager()
        self.overlay = ViewerOverlay()
        self.menubar = HortMenuBarAgent(self)
        self._server_thread = None
        self._server_loop = None

    def run(self):
        """Start the app. Blocks on NSApplication.run() (main thread)."""
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        # ↑ "Accessory" = no Dock icon, status bar only

        # Start the FastAPI server on a background thread
        self.start_server()

        # Block on AppKit run loop (main thread) — handles status bar + overlay
        AppKit.NSApp.run()

    def start_server(self):
        """Start the FastAPI server in a background thread."""
        if self._server_thread and self._server_thread.is_alive():
            return

        self._server_thread = threading.Thread(
            target=self._run_server, daemon=True, name="hort-server"
        )
        self._server_thread.start()
        self.menubar.update_status(running=True, viewer_count=0)

        if self.power.is_preventing_sleep or self.menubar.sleep_prevention_enabled:
            self.power.prevent_sleep()

    def _run_server(self):
        """Runs in background thread — owns the asyncio event loop."""
        self._server_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._server_loop)

        from hort.app import create_app, _run_servers
        from hort.cert import ensure_certs, CERTS_DIR
        from hort.network import get_lan_ip

        app = create_app(dev_mode=False)
        lan_ip = get_lan_ip()
        cert_path, key_path = ensure_certs(CERTS_DIR, lan_ip=lan_ip)

        self._server_loop.run_until_complete(
            _run_servers(cert_path, key_path)
        )

    def stop_server(self):
        """Stop the server gracefully."""
        if self._server_loop:
            self._server_loop.call_soon_threadsafe(self._server_loop.stop)
        self.power.allow_sleep()
        self.menubar.update_status(running=False, viewer_count=0)
        self.overlay.hide()

    def quit(self):
        """Full shutdown."""
        self.stop_server()
        self.power.allow_sleep()
        AppKit.NSApp.terminate_(None)
```

#### Entry Point: Two Modes

```python
# hort/desktop/main.py (or integrated into existing run.py)

def main():
    headless = "--headless" in sys.argv or "--dev" in sys.argv or sys.platform != "darwin"

    if headless:
        # No GUI — asyncio on main thread, same as today
        from hort.app import main as server_main
        server_main()
    else:
        # Status bar mode — AppKit on main thread, server on background thread
        from hort.desktop.app import HortDesktopApp
        app = HortDesktopApp()
        app.run()
```

**Usage:**
```bash
hort              # → status bar icon + server (default on macOS)
hort --headless   # → server only, no GUI (Linux, Docker, SSH, dev)
hort --dev        # → dev mode with uvicorn --reload (implies headless)
```

**Thread model (both modes):**

| | Main thread | Background thread |
|---|---|---|
| **Default (macOS)** | AppKit run loop (status bar, overlay) | asyncio (FastAPI, WebSockets) |
| **Headless** | asyncio (FastAPI, WebSockets) | — |

**Communication between threads:**
- main→background: `loop.call_soon_threadsafe()`
- background→main: `NSOperationQueue.mainQueue().addOperationWithBlock_()`

### 5. Permissions UX

Hort needs two macOS permissions:
1. **Screen Recording** — for window capture (Quartz `CGWindowListCreateImage`)
2. **Accessibility** — for input simulation (CGEvent posting, AX API)

These currently require manual trips to System Settings. For a non-techie, we should:

```python
# hort/desktop/permissions.py

def check_permissions() -> dict[str, bool]:
    """Check which permissions are granted."""
    import Quartz
    import ApplicationServices

    screen_recording = Quartz.CGPreflightScreenCaptureAccess()
    accessibility = ApplicationServices.AXIsProcessTrusted()

    return {
        "screen_recording": screen_recording,
        "accessibility": accessibility,
    }

def request_permissions():
    """Prompt for permissions if not granted."""
    import Quartz
    import ApplicationServices

    if not Quartz.CGPreflightScreenCaptureAccess():
        # This triggers the macOS permission dialog
        Quartz.CGRequestScreenCaptureAccess()

    if not ApplicationServices.AXIsProcessTrusted():
        # Open System Settings → Privacy → Accessibility with our app highlighted
        options = {AppKit.kAXTrustedCheckOptionPrompt: True}
        ApplicationServices.AXIsProcessTrustedWithOptions(options)
```

On first launch, we check and prompt. The menu bar can show a warning icon if permissions are missing.

### 6. Auto-Start on Login (LaunchAgent)

```python
# hort/desktop/autostart.py

PLIST_PATH = Path("~/Library/LaunchAgents/com.openhort.agent.plist").expanduser()

PLIST_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openhort.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{app_path}/Contents/MacOS/Hort</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""

def install_launch_agent(app_path: str):
    """Install LaunchAgent for auto-start on login."""
    content = PLIST_CONTENT.format(app_path=app_path)
    PLIST_PATH.write_text(content)
    # Load immediately
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)

def uninstall_launch_agent():
    """Remove LaunchAgent."""
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.unlink()

def is_launch_agent_installed() -> bool:
    return PLIST_PATH.exists()
```

### 7. Packaging & Distribution

#### py2app Bundle

`py2app` creates a standard macOS `.app` bundle from a Python project. It bundles the Python interpreter, all dependencies, and our code into a self-contained app.

```python
# setup_app.py (py2app configuration)

from setuptools import setup

APP = ["hort/desktop/main.py"]
DATA_FILES = [
    ("static", ["hort/static/"]),       # Web UI
    ("icons", ["resources/hort.icns"]),  # App icon
]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "resources/hort.icns",
    "plist": {
        "CFBundleName": "Hort",
        "CFBundleDisplayName": "Hort",
        "CFBundleIdentifier": "com.openhort.desktop",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,  # No Dock icon (menu bar only)
        "NSScreenCaptureUsageDescription":
            "Hort needs screen recording access to capture windows for remote viewing.",
        "NSAppleEventsUsageDescription":
            "Hort needs automation access to switch between windows and Spaces.",
    },
    "packages": ["hort", "uvicorn", "fastapi", "pydantic"],
    "includes": [
        "Quartz", "AppKit", "Foundation",
        "ApplicationServices",
    ],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
```

**Build:**
```bash
python setup_app.py py2app
# → dist/Hort.app
```

#### DMG Creation

```bash
# scripts/build-dmg.sh

create-dmg \
  --volname "Hort" \
  --volicon "resources/hort.icns" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "Hort.app" 150 190 \
  --app-drop-link 450 190 \
  --background "resources/dmg-background.png" \
  "dist/Hort-0.1.0.dmg" \
  "dist/Hort.app"
```

Result: a `.dmg` file the user opens, drags Hort to Applications, done.

#### Code Signing & Notarization

Required for running on other Macs without Gatekeeper warnings.

```bash
# 1. Sign with Developer ID
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Your Name (TEAM_ID)" \
  dist/Hort.app

# 2. Create DMG (as above)

# 3. Notarize with Apple
xcrun notarytool submit dist/Hort-0.1.0.dmg \
  --apple-id "your@email.com" \
  --team-id "TEAM_ID" \
  --password "@keychain:AC_PASSWORD" \
  --wait

# 4. Staple the notarization ticket
xcrun stapler staple dist/Hort-0.1.0.dmg
```

**Cost:** Apple Developer Program — $99/year. Required for Developer ID signing outside the App Store.

### 8. Auto-Updates

Since we're not on the App Store, we need our own update mechanism.

**Option A: Sparkle Framework** (recommended)
- Industry standard for non-App Store Mac apps (used by Firefox, VLC, etc.)
- Checks an appcast XML feed for new versions
- Downloads, verifies signature, replaces app bundle
- Can be integrated via PyObjC bridge or bundled as a framework
- Requires hosting the appcast XML + DMG somewhere (GitHub Releases works)

**Option B: Simple version check**
- On startup, fetch `https://api.github.com/repos/openhort/openhort/releases/latest`
- Compare version, show "Update available" in menu bar menu
- User clicks → opens download page
- Less slick but much simpler to implement

**Decision:** Start with Option B (simple check + download link). Add Sparkle later if update friction becomes a problem.

## Configuration

Settings stored in `~/Library/Application Support/Hort/config.json`:

```json
{
    "server": {
        "port": 8940,
        "auto_start": true
    },
    "power": {
        "prevent_system_sleep": true,
        "prevent_display_sleep": false
    },
    "overlay": {
        "enabled": true,
        "position": "top-center",
        "auto_hide_seconds": 0
    },
    "autostart": {
        "launch_on_login": true
    }
}
```

## File Structure

```
hort/desktop/
  __init__.py
  main.py              # Entry point: create app, run
  app.py               # HortDesktopApp — orchestrates everything
  menubar.py           # Menu bar status item + dropdown menu
  power.py             # IOPMAssertion sleep prevention
  overlay.py           # Floating viewer warning banner
  sck_capture.py       # ScreenCaptureKit capture provider (replaces Quartz)
  permissions.py       # Screen Recording / Accessibility checks
  autostart.py         # LaunchAgent install/uninstall
  config.py            # Desktop app settings (separate from server config)

resources/
  hort.icns            # App icon (all sizes)
  hort-menubar.png     # Menu bar icon (16x16, 32x32 @2x)
  hort-menubar-active.png
  dmg-background.png   # DMG installer background

scripts/
  build-app.sh         # py2app + code sign + notarize + DMG
  setup_app.py         # py2app configuration
```

## Viewer Tracking — Server-Side Hook

To know when viewers connect/disconnect, we need to expose this from the existing WebSocket handling. The stream WebSocket (`/ws/stream/{session_id}`) already tracks connections.

```python
# Integration point in hort/stream.py or hort/app.py

# Callback system for viewer events
_viewer_callbacks: list[Callable[[int], None]] = []

def on_viewer_change(callback: Callable[[int], None]):
    """Register callback for viewer count changes."""
    _viewer_callbacks.append(callback)

def _notify_viewer_change(count: int):
    for cb in _viewer_callbacks:
        try:
            cb(count)
        except Exception:
            pass

# In the stream WebSocket handler:
async def stream_ws(websocket, session_id):
    active_streams.add(websocket)
    _notify_viewer_change(len(active_streams))
    try:
        # ... existing stream logic
    finally:
        active_streams.discard(websocket)
        _notify_viewer_change(len(active_streams))
```

The desktop app registers its callback on startup:

```python
from hort.stream import on_viewer_change

def _on_viewer_change(count: int):
    menubar.update_status(running=True, viewer_count=count)
    if count > 0:
        overlay.show(count)
    else:
        overlay.hide()

on_viewer_change(_on_viewer_change)
```

## Permissions: From Painful to One-Click

### The Current Problem

Today hort runs as a Python script inside iTerm. This causes two permission headaches:

1. **Permission is attributed to the terminal, not to hort.** macOS grants Screen Recording to the *process* that calls `CGWindowListCreateImage`. Since that's a Python interpreter spawned by iTerm, the user has to grant Screen Recording to iTerm — giving iTerm blanket capture ability for everything, not just hort.

2. **Per-app re-prompting on macOS 15+.** Starting with Sequoia, Apple tightened `CGWindowListCreateImage`. Even with Screen Recording granted, the legacy Quartz API triggers per-app consent dialogs ("iTerm wants to record Window X"). These pop up for each new application's windows, and periodically re-prompt. This is the "one by one" experience.

### The Fix: `.app` Bundle + ScreenCaptureKit

Both problems are solved by two changes that reinforce each other:

#### Fix 1: Bundle as Hort.app

When hort runs as `Hort.app` (via py2app), macOS attributes the Screen Recording permission to `com.openhort.desktop` — our bundle ID. The user grants permission once to "Hort" in System Settings, not to their terminal.

This alone improves things significantly, but the legacy Quartz API still triggers periodic re-consent on macOS 15+.

#### Fix 2: Migrate capture from Quartz to ScreenCaptureKit

ScreenCaptureKit (macOS 12.3+) is Apple's modern replacement for `CGWindowListCreateImage`. It has a fundamentally different permission model:

| | Legacy Quartz (`CGWindowListCreateImage`) | ScreenCaptureKit (`SCStream`) |
|---|---|---|
| **Permission grant** | Per-app, periodic re-prompt (macOS 15+) | One-time grant, covers all content |
| **Consent UI** | System Settings manual toggle + per-app popups | Native system picker OR blanket grant |
| **Performance** | CPU-based screenshot, one frame at a time | GPU-accelerated, continuous stream |
| **API model** | Snapshot (poll → capture → encode) | Stream (configure once → frames delivered) |
| **Window listing** | Separate API (`CGWindowListCopyWindowInfo`) | Included (`SCShareableContent`) |
| **Output format** | CGImage → manual conversion | CMSampleBuffer → CVPixelBuffer (direct) |

**ScreenCaptureKit gives us one permission grant that covers all windows, forever.** No per-app popups. No periodic re-prompts. The user sees one system dialog on first launch, clicks Allow, done.

### ScreenCaptureKit Integration

The existing `CaptureProvider` interface in `hort/ext/types.py` already abstracts capture behind a clean boundary:

```python
class CaptureProvider(ABC):
    def capture_window(self, window_id: int, max_width: int = 800, quality: int = 70) -> bytes | None:
        ...
```

We add a new provider that uses ScreenCaptureKit internally, without changing the interface.

#### New: SCK-based Capture Provider

```python
# hort/desktop/sck_capture.py

import ScreenCaptureKit  # via pyobjc-framework-ScreenCaptureKit
import CoreMedia
import CoreVideo
from hort.ext.types import CaptureProvider

class SCKCaptureProvider(CaptureProvider):
    """Window capture using ScreenCaptureKit.

    Advantages over legacy Quartz:
    - Single permission grant (no per-app re-prompts)
    - GPU-accelerated capture
    - Continuous streaming support (future: direct frame pump)
    """

    def __init__(self):
        self._content: SCShareableContent | None = None
        self._refresh_content()

    def _refresh_content(self):
        """Refresh the list of shareable windows/displays."""
        # SCShareableContent.getWithCompletionHandler_ is async;
        # we wrap it for sync use
        import threading
        event = threading.Event()
        result = {}

        def handler(content, error):
            if content:
                result["content"] = content
            event.set()

        ScreenCaptureKit.SCShareableContent.getShareableContentWithCompletionHandler_(handler)
        event.wait(timeout=5.0)
        self._content = result.get("content")

    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None:
        """Capture a single window via ScreenCaptureKit."""
        if self._content is None:
            self._refresh_content()
        if self._content is None:
            return None

        # Find the SCWindow matching our window_id
        target_window = None
        for window in self._content.windows():
            if window.windowID() == window_id:
                target_window = window
                break
        if target_window is None:
            return None

        # Create a content filter for just this window
        content_filter = ScreenCaptureKit.SCContentFilter.alloc() \
            .initWithDesktopIndependentWindow_(target_window)

        # Configure capture
        config = ScreenCaptureKit.SCStreamConfiguration.alloc().init()
        config.setWidth_(max_width)
        # Compute height from aspect ratio
        bounds = target_window.frame()
        if bounds.size.width > 0:
            aspect = bounds.size.height / bounds.size.width
            config.setHeight_(int(max_width * aspect))
        config.setPixelFormat_(CoreVideo.kCVPixelFormatType_32BGRA)
        config.setShowsCursor_(False)

        # Single-frame capture (macOS 14+: captureImage)
        import threading
        event = threading.Event()
        result = {}

        def image_handler(image, error):
            if image:
                result["image"] = image
            event.set()

        ScreenCaptureKit.SCScreenshotManager \
            .captureImageWithFilter_configuration_completionHandler_(
                content_filter, config, image_handler
            )
        event.wait(timeout=3.0)

        cg_image = result.get("image")
        if cg_image is None:
            return None

        # Convert CGImage → JPEG bytes (reuse existing PIL path)
        from hort.screen import _cgimage_to_pil
        import io
        from PIL import Image

        pil_image = _cgimage_to_pil(cg_image)
        if pil_image is None:
            return None

        buf = io.BytesIO()
        pil_image.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
```

#### Window Listing Bonus

ScreenCaptureKit's `SCShareableContent` also provides window listing, which can supplement or replace `CGWindowListCopyWindowInfo`:

```python
# SCShareableContent gives us:
content.windows()   # → [SCWindow] — each has windowID, title, owningApplication, frame, isOnScreen
content.displays()  # → [SCDisplay] — each display/monitor
content.applications()  # → [SCRunningApplication] — each app with its windows

# SCWindow properties:
window.windowID()              # Same ID as kCGWindowNumber
window.title()                 # Window title (no separate permission needed!)
window.owningApplication()     # → SCRunningApplication
window.frame()                 # CGRect bounds
window.isOnScreen()            # Visibility
window.isActive()              # Foreground status
```

This is significant: with the Quartz API, `kCGWindowName` returns empty strings unless Screen Recording is granted. With ScreenCaptureKit, window titles come through as part of the normal API — no separate permission gate for listing vs capturing.

#### Streaming: Future Optimization

The current hort stream loop is poll-based: timer fires → capture → encode → send. ScreenCaptureKit enables a push-based model where the OS delivers frames continuously:

```python
# Future: SCStream for continuous capture (replaces the poll timer)
stream = ScreenCaptureKit.SCStream.alloc().initWithFilter_configuration_delegate_(
    content_filter, config, delegate
)
stream.addStreamOutput_type_sampleHandlerQueue_error_(
    output_handler,
    ScreenCaptureKit.SCStreamOutputTypeSCreen,
    dispatch_queue,
    None,
)
stream.startCaptureWithCompletionHandler_(...)
# → output_handler receives CMSampleBuffer frames continuously
```

This would be a significant performance improvement for the streaming use case, but it's a larger refactor. The single-frame `SCScreenshotManager.captureImage` approach above is a drop-in replacement that preserves the existing poll model.

### Permission Flow for Non-Techies

With ScreenCaptureKit in the `.app` bundle, the first-launch experience becomes:

```
1. User opens Hort.app
2. macOS shows: "Hort would like to capture your screen"
   [Don't Allow]  [Allow]
3. User clicks Allow → done. All windows capturable. No more prompts.
```

vs the current experience:

```
1. User opens terminal (what's a terminal?)
2. Types `poetry run python run.py` (what?)
3. macOS shows: "iTerm wants to record your screen"
4. User goes to System Settings → Privacy → Screen Recording → enables iTerm
5. First window capture works, second app's window triggers: "Allow iTerm to record App X?"
6. Repeat for each application...
7. A month later, macOS re-prompts for everything
```

### Migration Path

The `CaptureProvider` interface doesn't change. We add `SCKCaptureProvider` as an alternative implementation:

```python
# In the macOS extension (provider.py), detect and prefer ScreenCaptureKit:

def capture_window(self, window_id: int, max_width: int = 800, quality: int = 70) -> bytes | None:
    if self._sck_provider:
        return self._sck_provider.capture_window(window_id, max_width, quality)
    # Fallback to legacy Quartz for macOS < 12.3 or terminal mode
    from hort.screen import capture_window
    return capture_window(window_id, max_width, quality)
```

The legacy Quartz path stays for:
- Dev mode (running from terminal, where SCK still prompts for the terminal)
- macOS < 12.3 (unlikely but costs nothing to keep)
- Fallback if SCK fails for any reason

### Dependency

```toml
# pyproject.toml — add alongside existing pyobjc packages
"pyobjc-framework-ScreenCaptureKit>=10.0; sys_platform == 'darwin'",
```

## Limitations & Edge Cases

| Issue | Mitigation |
|---|---|
| **Clamshell sleep** — MacBook lid closed, no external display | Cannot prevent. macOS forces sleep. Document: "connect external display or use a clamshell-mode tool" |
| **Screen Recording permission** — requires manual System Settings toggle | Prompt on first launch, show clear instructions, add "Fix Permissions" menu item that opens the right Settings pane |
| **py2app bundle size** — Python + deps = ~100-200 MB | Acceptable for a desktop app. Strip debug symbols, exclude test files |
| **App Translocation** — macOS quarantines apps opened from DMG without moving to /Applications | The installer background image says "Drag to Applications". Notarization helps. |
| **Hardened Runtime** — required for notarization, restricts some capabilities | Needs entitlements for screen capture, accessibility. py2app supports this via plist config |
| **Apple Silicon + Intel** — universal binary | py2app can build universal2 if both Python architectures are available. Or ship separate builds. |

## Implementation Order

### Phase 1: ScreenCaptureKit (can ship independently of the desktop app)

1. **`hort/desktop/sck_capture.py`** — SCK-based `CaptureProvider` implementation
2. **Wire into macOS extension** — prefer SCK when available, fallback to Quartz
3. **Add `pyobjc-framework-ScreenCaptureKit`** dependency
4. **Test** — verify single permission grant covers all windows

This alone eliminates the per-window prompting, even when running from a terminal. It's the highest-value change.

### Phase 2: Desktop App Shell

5. **`hort/desktop/power.py`** — sleep prevention (standalone, testable independently)
6. **`hort/desktop/overlay.py`** — floating banner (can test with a simple script)
7. **`hort/desktop/menubar.py`** — menu bar agent with static menu
8. **`hort/desktop/app.py`** — wire together: AppKit run loop + server thread
9. **Viewer tracking hook** — add callback system to `hort/stream.py`

### Phase 3: Polish & Distribution

10. **`hort/desktop/permissions.py`** — permission checks and prompts
11. **`hort/desktop/autostart.py`** — LaunchAgent management
12. **`hort/desktop/config.py`** — persistent settings
13. **`setup_app.py`** — py2app configuration
14. **`scripts/build-app.sh`** — full build pipeline (sign, notarize, DMG)
15. **Auto-update check** — version comparison + menu item

Phase 1 can ship as a standalone improvement today. Phase 2 changes no existing code except the viewer callback hook in `stream.py`. Phase 3 is packaging and polish.
