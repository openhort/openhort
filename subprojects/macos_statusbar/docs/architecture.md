# Architecture

## Process Model

The status bar app is a **standalone macOS process** — separate from the openhort server. It communicates with the server exclusively through HTTP and WebSocket APIs. This separation is deliberate:

- The status bar stays responsive even if the server hangs, crashes, or is restarting
- The server can be started/stopped/restarted without affecting the status bar
- The status bar can detect and attach to a server that was started externally (from terminal, from a LaunchAgent, from another tool)
- No import-time coupling to the `hort` package — the status bar depends only on `httpx`, `websockets`, and `pyobjc`

```
┌─────────────────────────────────────────────────────────┐
│                  macOS Status Bar Process                │
│                                                         │
│  Main Thread (AppKit)         Background Thread         │
│  ┌─────────────────────┐     ┌───────────────────────┐  │
│  │                     │     │                       │  │
│  │  NSApplication      │     │  asyncio event loop   │  │
│  │  ├─ NSStatusItem    │     │  ├─ ServerBridge      │  │
│  │  │  └─ NSMenu       │◄───►│  │  ├─ HTTP polling   │  │
│  │  ├─ ViewerOverlay   │     │  │  ├─ WS status      │  │
│  │  │  └─ NSWindow     │     │  │  └─ subprocess mgmt│  │
│  │  └─ PowerManager    │     │  └─ Plugin poller     │  │
│  │     └─ IOPMAssertion│     │                       │  │
│  └─────────────────────┘     └───────────────────────┘  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Settings (~/Library/Application Support/...)     │   │
│  │  └─ statusbar.json (persisted across launches)   │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP / WebSocket
                     ▼
┌─────────────────────────────────────────────────────────┐
│              openhort server (separate process)          │
│  ├─ FastAPI on :8940 (HTTP) and :8950 (HTTPS)           │
│  ├─ WebSocket /ws/control, /ws/stream                   │
│  ├─ Plugin registry                                      │
│  └─ Session registry                                     │
└─────────────────────────────────────────────────────────┘
```

## Thread Model

macOS requires that all AppKit UI operations run on the **main thread**. The NSApplication run loop owns the main thread and cannot share it. Meanwhile, the server bridge needs an asyncio event loop for non-blocking HTTP and WebSocket polling.

Solution: two threads, clear ownership.

| Thread | Owner | Runs | Examples |
|--------|-------|------|----------|
| Main | AppKit (`NSApp.run()`) | All UI: menu updates, overlay show/hide, icon changes, alerts, pasteboard | `_status_item.setMenu_(...)`, `_window.orderFront_(...)` |
| Background (daemon) | asyncio (`loop.run_forever()`) | All I/O: HTTP polling, WebSocket connections, subprocess management | `httpx.get(...)`, `websockets.connect(...)` |

### Thread Communication

**Background → Main** (status update arrived, need to update menu):
```python
AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
    lambda: self._do_update(running, observers, version)
)
```
This is the only safe way to touch AppKit objects from a background thread. `addOperationWithBlock_` queues the block on the main thread's run loop. It's non-blocking for the caller.

**Main → Background** (user clicked Start Server):
```python
self._bg_loop.call_soon_threadsafe(
    lambda: asyncio.ensure_future(self.bridge.start_server_async())
)
```
`call_soon_threadsafe` is the asyncio equivalent — schedules a callback on the event loop from another thread.

### Why Not a Single Thread?

AppKit's `NSApp.run()` blocks forever — it is the run loop. There is no way to interleave asyncio coroutines with it. Alternatives considered:

| Approach | Problem |
|----------|---------|
| `asyncio.run()` on main thread | Can't call AppKit (crashes if not main thread) |
| `NSTimer` + sync polling | Blocks the run loop during HTTP calls, menu becomes unresponsive |
| `NSURLSession` (native async HTTP) | Works but loses the asyncio ecosystem (websockets, httpx). Mixing Obj-C async with Python async is fragile |
| PyObjC event loop integration | `PyObjCTools.AppHelper.runConsoleEventLoop()` exists but is poorly documented and doesn't support asyncio |

Two threads with dispatch is the simplest correct solution. It's the same model used by every macOS app with a networking layer.

## Startup Sequence

```
main()
  │
  ├─ Parse args (--help)
  ├─ Configure logging
  ├─ Check platform == darwin
  │
  └─ HortStatusBarApp()
       │
       ├─ PowerManager()                    # no-op until prevent_sleep() called
       ├─ ViewerOverlay()                   # no-op until show() called
       ├─ ServerBridge(on_status_change)    # creates httpx client, no connections yet
       ├─ MenuBarAgent(self)                # creates NSStatusItem + NSMenu
       │
       └─ .run()
            │
            ├─ NSApplication.sharedApplication()
            ├─ setActivationPolicy_(Accessory)    # no Dock icon
            │
            ├─ _init_state()
            │   ├─ Check autostart installed?     # reflect in menu
            │   ├─ Check permissions?              # show warning if missing
            │   ├─ power.prevent_sleep()           # if enabled in settings
            │   ├─ Check port 8940 in use?         # detect running server
            │   └─ Load settings from disk         # statusbar.json
            │
            ├─ _start_background_loop()
            │   └─ Thread("hort-statusbar-bg")
            │       └─ asyncio.new_event_loop()
            │           └─ bridge.start_polling()  # poll every 3s
            │
            └─ NSApp.run()                         # blocks forever (main thread)
```

## Shutdown Sequence

Triggered by "Quit openhort" menu item or `Cmd+Q` (if we register a global shortcut):

```
quit()
  │
  ├─ bg_loop.call_soon_threadsafe(loop.stop)    # stop polling
  ├─ power.allow_sleep()                         # release IOPMAssertions
  ├─ overlay.hide()                              # dismiss banner
  └─ NSApp.terminate_(None)                      # exits AppKit run loop
```

Note: stopping the background loop does NOT stop the openhort server. The server is a separate process and keeps running. The user explicitly stops it from the menu if desired. If the server was started by the status bar as a subprocess, it also keeps running — the subprocess is not killed on quit. This is intentional: the server should survive a status bar restart.

To stop the server AND quit: the user clicks "Stop Server" first, then "Quit". Or we can add a "Quit and Stop Server" option that does both.

## Data Flow: Polling Cycle

Every 3 seconds, the background thread runs one poll cycle:

```
_poll_loop (every 3s)
  │
  ├─ Check subprocess alive?
  │   └─ If exited → status.running = False, status.error = exit code
  │
  ├─ GET /api/statusbar/state                  # combined endpoint (Phase 2)
  │   │
  │   │  OR (Phase 1, before combined endpoint):
  │   ├─ GET /api/hash                         # server alive check
  │   ├─ POST /api/session → WS get_status     # observer count
  │   └─ GET /api/sessions/active              # viewer details (Phase 2)
  │
  ├─ Diff with previous status
  │   ├─ observers changed? → update icon, overlay, maybe notify
  │   ├─ running changed?   → update icon, menu labels
  │   └─ plugin data changed? → update plugin menu items
  │
  └─ Call on_status_change(new_status)
       │
       └─ Dispatches to main thread:
           ├─ menubar.update_server_status(...)
           ├─ menubar.update_viewers(...)
           ├─ menubar.update_plugins(...)
           ├─ overlay.show(count) / overlay.hide()
           └─ icon state change
```

## Error States

The status bar must handle the server being in any state:

| Server state | Status bar behavior |
|-------------|-------------------|
| Not running, never started | Icon gray, "Server: Stopped", Start button enabled |
| Starting (subprocess just spawned) | Icon gray with spinner text "Server: Starting…", poll until /api/hash responds |
| Running, healthy | Icon green, "Server: Running" |
| Running, viewers connected | Icon red, viewer count shown, overlay visible |
| Not responding (poll timeout) | Icon yellow, "Server: Not Responding", Start/Stop both enabled |
| Crashed (subprocess exited non-zero) | Icon yellow, "Server: Crashed (exit 1)", error in menu |
| Port in use by another process | "Server: Port 8940 in use", cannot start |

The status bar never crashes due to server state. Every HTTP call has a timeout. Every WebSocket connection attempt has a timeout. Connection errors are caught and reflected in the UI.

## Relationship to DESIGN.md

The existing `subprojects/macos_app/DESIGN.md` proposed embedding the server inside the status bar process (AppKit on main thread, FastAPI on background thread, same process). This architecture document takes a different approach: **separate processes**.

Reasons for the change:

1. **Isolation** — A server bug cannot crash the status bar. A status bar bug cannot crash the server.
2. **Restart independence** — Restart the server without losing the status bar icon. Restart the status bar without disconnecting viewers.
3. **Attach to external server** — The status bar can monitor a server started from terminal, from a LaunchAgent, or from another machine's P2P tunnel.
4. **Simpler testing** — The server bridge is just an HTTP/WS client. Mock the endpoints, test everything.
5. **No import conflicts** — The status bar doesn't import `hort.*`. No risk of triggering plugin loading, Quartz imports on the wrong thread, or circular dependencies.

The DESIGN.md approach is still valid for a hypothetical `hort` CLI entry point that combines both (`hort` = server + menu bar, `hort --headless` = server only). This concept focuses on the standalone status bar app.
