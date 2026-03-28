# Remote Viewing Safety

## Motivation

openhort streams your screen to remote viewers. This is powerful and useful — but it's also a privacy-sensitive capability. The machine owner must always know when their screen is being watched. This is not optional, not configurable, not dismissable. It's a hard guarantee.

The status bar app implements a **four-tier indicator system**. Each tier adds visibility and control. Together they ensure that remote viewing is impossible to hide from the machine owner.

## Tier 1: Icon State (always active, cannot disable)

The menu bar icon shows a **red dot** whenever `observer_count > 0`. This is the most basic and most reliable indicator.

### Properties

- **Always visible** — the menu bar is visible in every app, on every Space, in every context
- **Cannot be disabled** — there is no setting, no flag, no API to suppress the red dot when viewers are connected. It is hardcoded into the icon state machine.
- **Immediate** — updates within 3 seconds of a viewer connecting (poll interval)
- **Unambiguous** — red dot means someone is watching. Green dot means no one is watching. No interpretation needed.
- **Persistent** — stays red as long as any viewer is connected. Doesn't time out, doesn't fade.

### Why Non-Suppressible?

If the red dot could be turned off, a scenario becomes possible: someone gains access to the server (maybe they know the URL, maybe they have a token), connects to view the screen, and the machine owner never knows because they disabled the indicator.

By making the icon state unconditionally tied to the observer count, we guarantee that the physical user of the machine always has a visual signal. They can ignore it, but they cannot be unaware of it without actively choosing to hide the entire status bar icon (which is their prerogative — they'd be hiding the app entirely, not just the indicator).

### Implementation Detail

```python
# This logic has NO condition checking for user preferences.
# The red dot is always shown when observers > 0.
def _compute_icon_state(self, status: ServerStatus) -> IconState:
    if status.observers > 0:
        return IconState.VIEWING  # red dot — always, unconditionally
    if status.has_attention:
        return IconState.ATTENTION  # yellow dot
    if status.running:
        return IconState.RUNNING  # green dot
    return IconState.STOPPED  # no dot
```

## Tier 2: Floating Overlay Banner (default ON, can disable)

A native macOS window that floats above all other windows, showing a red banner with the viewer count.

### Visual Design

```
┌────────────────────────────────────────────────────┐
│  ●  Remote viewing active — 2 viewers              │
└────────────────────────────────────────────────────┘

Width:   320 points (auto-sizing to text)
Height:  32 points
Color:   rgba(217, 38, 38, 0.9) background, white text
Font:    System Medium, 13pt
Corner:  8pt radius
Shadow:  Standard NSWindow shadow
```

### Window Properties

| Property | Value | Why |
|----------|-------|-----|
| Level | `NSFloatingWindowLevel` | Above all normal windows, below screen savers |
| Opaque | `False` | Semi-transparent background |
| IgnoresMouseEvents | `True` | Click-through — doesn't interfere with using the Mac |
| CollectionBehavior | `CanJoinAllSpaces \| Stationary` | Visible on all Spaces, doesn't move with Space switches |
| StyleMask | `Borderless` | No title bar, close button, or resize handle |
| HasShadow | `True` | Subtle depth cue |

### Position

Default: **top-center** of the main screen, 45 points below the top edge (just below the menu bar).

```
┌─────────────────────────────────────────────────────┐
│  Menu bar                                           │
├─────────────────────────────────────────────────────┤
│           ┌──────────────────────────┐              │
│           │ ● Remote viewing — 2     │  ← here     │
│           └──────────────────────────┘              │
│                                                     │
│                    Desktop                          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

Configurable positions (in `statusbar.json`):
- `top-center` (default) — centered horizontally, below menu bar
- `top-right` — aligned with menu bar extras area, below menu bar
- `top-left` — aligned with Apple menu area, below menu bar

### Lifecycle

| Event | Overlay action |
|-------|---------------|
| `observer_count` 0 → 1 | Create window (if first time), show, set text |
| `observer_count` 1 → 2 | Update text ("2 viewers") |
| `observer_count` N → 0 | Hide window (don't destroy — reuse on next connection) |
| User disables in Settings | Hide window, don't show on future connections |
| User re-enables in Settings | If viewers currently connected, show immediately |

### Why Dismissable?

Unlike Tier 1 (icon), the overlay CAN be disabled. Reasons:
- Some users find floating banners distracting
- The overlay is supplementary — Tier 1 (icon) already provides the guarantee
- A user who knows about the overlay and consciously disables it has made an informed choice
- Forcing an undismissable floating window would be hostile UX

The overlay is **ON by default** and the setting to disable it is buried in the Settings submenu, not prominent. New users see the overlay. Experienced users who find it annoying can turn it off knowing the icon still indicates viewing.

## Tier 3: System Notification (default ON, can disable)

A standard macOS notification posted when the first viewer connects.

### Notification Content

```
┌─────────────────────────────────────────────────┐
│  🔴 openhort                                    │
│                                                  │
│  Someone is now viewing your screen              │
│  iPhone (Safari) connected to Desktop            │
│                                                  │
│  [Disconnect]           [Open openhort]          │
└─────────────────────────────────────────────────┘
```

### Trigger Rules

| Transition | Action |
|-----------|--------|
| 0 → 1 viewers | Post notification with first viewer's device info |
| 0 → N viewers (simultaneous) | Post notification: "N viewers connected" |
| N → M viewers (N > 0, M > N) | No notification (already notified about active viewing) |
| N → 0 → M viewers | Post notification again (viewing stopped and restarted) |

The key rule: only notify on the **0 → N transition**. If 3 viewers are connected and a 4th joins, no notification. The user already knows viewing is happening (from the first notification + icon + overlay).

### Implementation

macOS 10.14+: Use `UNUserNotificationCenter` (the modern notification framework):

```python
import UserNotifications

center = UserNotifications.UNUserNotificationCenter.currentNotificationCenter()

content = UserNotifications.UNMutableNotificationContent.alloc().init()
content.setTitle_("openhort")
content.setBody_(f"Someone is now viewing your screen")
content.setSubtitle_(f"{device_name} connected")
content.setSound_(UserNotifications.UNNotificationSound.defaultSound())

# Action buttons
disconnect_action = UserNotifications.UNNotificationAction.actionWithIdentifier_title_options_(
    "disconnect", "Disconnect", UserNotifications.UNNotificationActionOptionDestructive
)
open_action = UserNotifications.UNNotificationAction.actionWithIdentifier_title_options_(
    "open", "Open openhort", UserNotifications.UNNotificationActionOptionForeground
)
category = UserNotifications.UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
    "viewer_connected", [disconnect_action, open_action], [], 0
)
center.setNotificationCategories_({category})
content.setCategoryIdentifier_("viewer_connected")

request = UserNotifications.UNNotificationRequest.requestWithIdentifier_content_trigger_(
    "viewer_connected", content, None  # None trigger = deliver immediately
)
center.addNotificationRequest_withCompletionHandler_(request, None)
```

### Action Handling

When the user clicks a notification action:
- **Disconnect**: calls `POST /api/sessions/disconnect-all` (same as menu panic button)
- **Open openhort**: opens the browser viewer

### Permission

macOS requires notification permission. On first launch, request it:

```python
center.requestAuthorizationWithOptions_completionHandler_(
    UserNotifications.UNAuthorizationOptionAlert
    | UserNotifications.UNAuthorizationOptionSound,
    lambda granted, error: None
)
```

If the user denies notification permission, Tier 3 is silently disabled. Tiers 1 and 2 still work. The menu shows a note in Settings: "Notifications: Denied (enable in System Settings)".

## Tier 4: Disconnect Controls (always available)

The "Connected Viewers" submenu in the menu bar provides:
1. **Per-viewer visibility** — see exactly who is connected, what device, what they're viewing
2. **Individual disconnect** (future) — kick a specific viewer
3. **Disconnect All** — panic button, one click to cut all viewers

### Disconnect All — No Confirmation

This is deliberate. If someone is watching your screen and you want them gone immediately, a confirmation dialog ("Are you sure?") adds friction to a safety action. The action is easily reversible (viewers can reconnect), so the cost of an accidental click is low.

### Per-Viewer Disconnect (Future, Phase 4)

Each viewer line becomes clickable:

```
  Connected Viewers (2) ▸
    👁 iPhone (Safari) — Desktop    00:12:34   [× Disconnect]
    👁 iPad (Chrome)  — Terminal    00:03:21   [× Disconnect]
    ─────────────────────
    Disconnect All
```

Clicking the `×` disconnects that specific session:

```
DELETE /api/sessions/{session_id}
```

## Threat Model

The indicator system protects against these scenarios:

### Scenario 1: Authorized viewer connects normally
**What happens**: Viewer opens the browser UI, enters the URL, sees the screen.
**Indicator response**: All four tiers activate. Machine owner sees the red dot, overlay, and notification within 3 seconds.
**Outcome**: Machine owner is aware.

### Scenario 2: Someone finds the URL and connects without permission
**What happens**: An unauthorized person has the server URL (maybe they saw the QR code, found it in browser history, or scanned the network).
**Indicator response**: Identical to Scenario 1. The server doesn't distinguish authorized from unauthorized viewers — all connections trigger the indicator.
**Outcome**: Machine owner sees the connection and can disconnect.

### Scenario 3: Viewer tries to watch "silently"
**What happens**: A viewer connects, hoping the machine owner won't notice.
**Indicator response**: Tier 1 (icon) is unconditional. There is no WebSocket flag, no HTTP header, no API parameter that suppresses the indicator. The server increments `observer_count`, the status bar polls it, the red dot appears.
**Outcome**: Silent watching is not possible while the status bar is running.

### Scenario 4: Viewer connects when machine owner is away
**What happens**: Someone views the screen while the owner is at lunch.
**Indicator response**: All tiers activate. When the owner returns:
- Tier 1: Red dot is still visible (if viewer is still connected)
- Tier 3: Notification is in Notification Center (even if the banner was dismissed)
- Future: Connection history in the menu shows past sessions
**Outcome**: Owner sees evidence of the connection.

### Scenario 5: Status bar is not running
**What happens**: The server is started from terminal (`poetry run python run.py`) without the status bar.
**Indicator response**: None — the status bar is the indicator. If it's not running, there's no menu bar icon.
**Outcome**: This is a known limitation. Mitigation: when the server detects it's running without a status bar companion, it could log a warning. The autostart feature (LaunchAgent) ensures the status bar is always running on a configured machine.

### Scenario 6: Multiple monitors
**What happens**: The Mac has multiple displays. The menu bar is on the primary display.
**Indicator response**: Tier 1 (icon) — visible on primary display's menu bar. Tier 2 (overlay) — on the primary display by default (configurable to show on all displays in future). Tier 3 (notification) — appears on the active display.
**Outcome**: Owner sees at least the icon. Overlay may not be on the display they're looking at if they're on a secondary monitor. Future enhancement: show overlay on all connected displays.

## Smart Display Sleep

When viewers are connected, the status bar automatically prevents display sleep — even if the user hasn't enabled "Keep Display On" in settings.

Rationale: if the display sleeps, `CGWindowListCreateImage` captures either a black screen or the lock screen (depending on macOS version). The remote viewer sees nothing useful. Preventing display sleep while someone is viewing is a necessary part of the feature working correctly, not a user preference.

```python
def _on_status_change(self, status: ServerStatus) -> None:
    if status.observers > 0:
        # Force display awake while viewers connected
        self.power.prevent_sleep(prevent_display_sleep=True)
    else:
        # Revert to user's preference
        if self._settings.prevent_display_sleep:
            self.power.prevent_sleep(prevent_display_sleep=True)
        elif self._settings.prevent_system_sleep:
            self.power.prevent_sleep(prevent_display_sleep=False)
        else:
            self.power.allow_sleep()
```

This auto-behavior is noted in the Settings submenu:

```
  Settings ▸
    ✓ Prevent Sleep
      Keep Display On (auto while viewers connected)
```

The "(auto while viewers connected)" hint tells the user that display sleep is managed dynamically.

## Connection History (Future, Phase 4)

A log of recent connections persisted to disk:

```json
// ~/Library/Application Support/openhort/connection_history.json
[
  {
    "session_id": "abc123",
    "connected_at": "2026-03-28T14:30:00Z",
    "disconnected_at": "2026-03-28T14:42:15Z",
    "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)...",
    "device": "iPhone (Safari)",
    "viewed": "Desktop",
    "duration_seconds": 735
  }
]
```

Accessible from the menu:

```
  Connected Viewers ▸
    ...
    ─────────────────
    Recent connections (3)  ▸
      iPhone (Safari) — 12 min ago, viewed Desktop for 12:15
      iPad (Chrome) — 2 hours ago, viewed Terminal for 03:21
      Mac (Firefox) — yesterday, viewed iTerm2 for 45:02
```

This addresses Scenario 4 (viewer connects while owner is away). The owner can see who was watching and when, even after the session ended.

History is kept for the last 50 sessions or 30 days, whichever is less. Older entries are pruned on each save.
