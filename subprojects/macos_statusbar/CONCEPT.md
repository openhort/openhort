# macOS Status Bar — Concept

The status bar is the **always-visible nerve center** of openhort on macOS. It replaces the terminal with a native, glanceable control point: is anyone watching my screen? Is the server healthy? What's connected? — all answered by a single icon in the menu bar.

For plugins, the status bar is an **extension surface** — the same way plugins add UI panels in the browser, they contribute items to the native macOS menu. A network monitor shows bandwidth. The Telegram connector shows its bot status. The P2P extension shows active tunnels. Each plugin declares what it wants to surface, and the status bar renders it natively.

## Principles

1. **Privacy-first** — Remote viewing must be impossible to hide. The icon state is the user's hard guarantee that they know when someone is watching. This cannot be suppressed.
2. **Glanceable** — The icon alone tells you: stopped (gray), running (green), someone watching (red + count), problem (yellow). No menu click needed for the critical question.
3. **Native** — Feels like iStat Menus or Amphetamine. Direct PyObjC, no Electron, no web views in menus. Template icons that adapt to light/dark mode.
4. **Extensible** — Plugins contribute menu sections through manifest declarations and the existing `get_status()` protocol. No status bar code changes needed to add a plugin.
5. **Non-blocking** — The status bar is a separate process that polls the server API. If the server hangs or crashes, the menu still works — it shows "Not Responding" and offers restart.

## Documents

| Document | What it covers |
|----------|---------------|
| [Architecture](docs/architecture.md) | Thread model, process lifecycle, AppKit/asyncio integration, data flow between components |
| [Icon & Visual States](docs/icon-and-states.md) | Icon design, state machine, transitions, badge rendering, dark/light mode, accessibility |
| [Menu Structure](docs/menu-structure.md) | Every section, every item, data sources, update mechanics, keyboard shortcuts, edge cases |
| [Remote Viewing Safety](docs/remote-viewing-safety.md) | Four-tier indicator system — icon, overlay, notification, disconnect — privacy guarantees, threat model |
| [Plugin Contributions](docs/plugin-contributions.md) | How plugins add menu items — manifest format, item types, data protocol, action dispatch, rendering rules, full examples |
| [System Controls](docs/system-controls.md) | Sleep prevention, autostart, permissions, settings persistence, server lifecycle |
| [Server API](docs/server-api.md) | All endpoints the status bar needs (existing + new), polling strategy, combined endpoint, error handling |

## Phases

### Phase 1: Core (done)
Icon with status dot, start/stop server, viewer count, open browser, copy URL, sleep prevention, viewer overlay banner, permission checks, autostart via LaunchAgent.

### Phase 2: Rich Status
Combined `/api/statusbar/state` endpoint, connected viewers submenu with per-viewer detail and disconnect, targets submenu, system notification on first viewer, auto display-sleep when viewers connected, QR popup, settings persistence, log viewer.

### Phase 3: Plugin Integration
`statusbar` manifest key in extension.json, plugin-contributed menu items (live_status, toggle, action, link), action dispatch endpoint, template interpolation, icon mapping.

### Phase 4: Advanced
Per-viewer bandwidth stats, global hotkey, mini live preview in menu (NSView), connection history, py2app packaging, DMG builder, Sparkle auto-update.
