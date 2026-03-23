# Telegram Bot Integration for Openhort

## Telegram Bot API Overview

The Telegram Bot API is **HTTP-only** — no WebSocket, no persistent push channel. Communication works via:

- **Polling (`getUpdates`)** — bot long-polls Telegram's servers for updates
- **Webhooks (`setWebhook`)** — Telegram pushes updates to your HTTPS endpoint (ports 443, 80, 88, 8443)

These are mutually exclusive. Webhooks are more efficient for production.

---

## What's Possible

### 1. On-Demand Screenshots (High Value)

Send a window screenshot to the user on command.

- `/screenshot [app_name]` → capture window via hort's `CaptureProvider` → `sendPhoto` to Telegram
- Telegram accepts photos up to **10 MB** (cloud API), auto-compresses
- For lossless quality, send as `sendDocument` (up to **50 MB** cloud, **2 GB** self-hosted local API server)
- Can send media groups (`sendMediaGroup`) for multi-window snapshots
- **Latency**: capture (~50ms) + JPEG encode + upload to Telegram (~200-500ms) = sub-second for single shots

### 2. Window Listing & Selection

- `/windows` → list all windows with inline keyboard buttons for selection
- `/windows [filter]` → filter by app name
- Inline keyboards allow tapping a window name → triggers screenshot or stream
- `/spaces` → list virtual desktops, switch between them

### 3. Periodic Monitoring / Timelapse

- Send screenshots at intervals (e.g., every 30s, 1m, 5m) via hort's scheduler system
- Use `editMessageMedia` to update a single message with the latest frame (avoids chat spam)
- Or send a new photo each interval for a timeline view
- Rate limit: ~30 messages/sec per bot, ~20 messages/min per group chat

### 4. Input Injection (Remote Control via Commands)

- `/click <x> <y>` → send click at normalized coordinates
- `/type <text>` → inject keyboard input
- `/key <key> [modifiers]` → send special keys (enter, escape, tab, arrows, F1-F12)
- `/scroll <direction>` → scroll up/down/left/right
- Inline keyboards for common actions (e.g., "Play/Pause", "Next Tab", "Close Window")
- Callback queries give instant feedback without new messages

### 5. Terminal Command Execution (High Value)

- `/run <command>` → spawn PTY, execute command, return stdout as text message
- `/shell` → start an interactive-ish session (user sends messages, bot sends output)
- Text messages limited to **4,096 characters** — truncate or paginate long output
- Send large output as a `sendDocument` (text file)
- Terminal scrollback buffer (200KB) available for history

### 6. System Monitoring Alerts

Leverage existing plugins to push alerts:

- **System Monitor** → alert on high CPU/memory/disk via `sendMessage`
- **Process Manager** → notify when a process crashes or starts
- **Network Monitor** → bandwidth alerts
- **Disk Usage** → low disk space warnings
- Scheduler-based: poll metrics at intervals, send Telegram message when threshold exceeded

### 7. Multi-Target Management

- `/targets` → list all connected targets (macOS, Linux, Docker containers)
- `/switch <target>` → change active target
- All screenshot/input/terminal commands scoped to active target
- Inline keyboard for quick target switching

### 8. Token & Access Management

- `/token` → generate temporary access token, send as QR code image (`sendPhoto`)
- `/token permanent` → generate permanent key
- `/revoke` → revoke all temporary tokens
- `/tunnel` → check cloud proxy status
- Useful for granting quick access to someone else

### 9. Plugin-Driven Extensions

The plugin system's `IntentMixin` + `MCPMixin` map naturally to bot commands:

- Each plugin can register Telegram commands
- Scheduler jobs can trigger Telegram notifications
- Intent handlers (photo, GPS, file, URL) → forward Telegram media to plugins
- e.g., send a photo to the bot → camera-scan plugin processes QR/barcode → returns result

### 10. Mini App (Full UI Inside Telegram)

Telegram's **Web Apps (Mini Apps)** are the most powerful integration:

- Embed the entire openhort Quasar UI inside Telegram's WebView
- Full JavaScript execution — can open WebSocket connections to hort server
- Real-time streaming works (WebSocket → canvas, same as browser)
- Full input injection (touch → mouse mapping)
- Full-screen mode (portrait/landscape)
- Launch from inline keyboard button, menu button, or direct link
- Authentication via Telegram's `initData` — can verify user identity server-side
- Access device sensors: geolocation, accelerometer, gyroscope, biometrics

**This is the closest to "hort in your pocket via Telegram".**

---

## What's NOT Possible (or Severely Limited)

### 1. Real-Time Video Streaming

**Not possible via messages.** Telegram has no WebSocket or persistent streaming channel for media. You cannot push JPEG frames at 10-60 FPS through `sendPhoto`.

- `sendPhoto` at 30/sec would hit rate limits and produce terrible UX (chat flooded with images)
- `sendVideo` / `sendAnimation` require a finished file, not a live stream
- `editMessageMedia` can update a photo in-place but still limited by rate limits (~30/sec theoretical, practical much lower in groups)
- **Workaround**: Mini App with WebSocket (see above) — this IS real-time

### 2. Low-Latency Interactive Control

**Severely limited via messages.** The round-trip for "user taps button → bot receives callback → bot sends input to hort → hort responds → bot sends screenshot" is 500ms-2s minimum.

- Inline keyboard callbacks are fast (~100-200ms) but still not interactive enough for mouse dragging, scrolling, or gaming
- Keyboard input via messages is too slow for real-time typing
- **Workaround**: Mini App gives near-native latency via direct WebSocket

### 3. Persistent Bidirectional Channel

**Not possible.** Telegram bots communicate via request-response (HTTP). There's no way to maintain a persistent connection from Telegram to your bot for push updates.

- Polling (`getUpdates`) has inherent latency (long-poll timeout, typically 10-30s)
- Webhooks are push-to-bot but bot-to-user still requires explicit `sendMessage` calls
- Cannot "subscribe" a user to a live feed
- **Workaround**: Webhooks + proactive `sendMessage` for alerts; Mini App for real-time

### 4. Binary Data Streaming

**Not possible.** Telegram messages are discrete — text, photo, video, document. No binary WebSocket equivalent.

- hort's stream WebSocket sends raw JPEG bytes continuously — no Telegram equivalent
- Terminal I/O (binary PTY data) can't stream to Telegram in real-time
- **Workaround**: batch terminal output, send as text messages with delay

### 5. Full Keyboard Input

**Limited.** Telegram messages are UTF-8 text. Mapping to keyboard events is lossy:

- No modifier key state (can't hold Shift while clicking)
- No key-up/key-down events, only "key pressed"
- Special keys need explicit syntax (`/key ctrl+c`, `/key F5`)
- Copy/paste shortcuts need translation
- **Workaround**: predefined inline keyboard layouts for common shortcuts; Mini App for full keyboard

### 6. Mouse Precision

**Limited via chat interface.** Users can't point-and-click on a screenshot in a Telegram message.

- Could overlay a coordinate grid on screenshots
- Could use inline keyboards for quadrant-based navigation ("top-left", "center", etc.)
- Could accept coordinates as text (`/click 0.5 0.3`)
- **Workaround**: Mini App renders the stream and captures touch events natively

### 7. Large File Transfers

**Cloud API limits**: 50 MB upload, 20 MB download per file.

- Screenshots are typically 50-500 KB (fine)
- Video recordings or large documents may exceed limits
- **Workaround**: self-hosted Telegram Bot API server raises limit to 2 GB; or upload to hort's file store and send a link

### 8. Group Chat Noise

**Not ideal for shared chats.** Bot commands and responses create message noise.

- Every interaction is a visible message (or edited message)
- No "private channel" within a group for bot output
- **Workaround**: use bot in private chat only; or use inline mode (results stay ephemeral until selected)

---

## Architecture Recommendation

### Tier 1: Command Bot (Simple, High Value)

```
Telegram User ←→ Telegram Bot API ←→ Bot Server ←→ Hort Control WS
```

- Bot server connects to hort as a WebSocket client (same as the browser UI)
- Commands map to control messages: `/windows` → `list_windows`, `/screenshot` → `get_thumbnail`
- Responses sent back as Telegram messages/photos
- Polling or webhook — either works
- **Best for**: monitoring, alerts, quick screenshots, running commands

### Tier 2: Mini App (Full Experience)

```
Telegram User → Opens Mini App → WebView loads hort UI → Direct WebSocket to hort
```

- The existing `index.html` (or a simplified version) runs inside Telegram's WebView
- Full streaming, input, terminal — everything works as in browser
- Auth via Telegram's `initData` + hort token
- **Best for**: actual remote control, interactive use

### Tier 3: Hybrid

- Command bot for alerts, quick actions, screenshots
- "Open Viewer" button launches Mini App for full interactive control
- Best of both worlds

---

## Telegram API Constraints Summary

| Constraint | Value | Impact |
|---|---|---|
| Text message length | 4,096 chars | Truncate terminal output |
| Caption length | 1,024 chars | Brief descriptions only |
| Photo upload (cloud) | 10 MB | Fine for screenshots |
| File upload (cloud) | 50 MB | May need chunking for video |
| File download (cloud) | 20 MB | |
| File upload (local API) | 2 GB | Self-hosted option |
| Rate limit (per bot) | ~30 msg/sec | No frame streaming |
| Rate limit (per group) | ~20 msg/min | Very limited in groups |
| Webhook ports | 443, 80, 88, 8443 | Must match for webhook mode |
| Update retention | 24 hours | Process updates promptly |
| Command name length | 32 chars | Keep command names short |
| Inline query results | Max 50 | Enough for window list |
| WebSocket support | None | HTTP only |
| Streaming support | None (except `sendMessageDraft` for text) | No live video |
| Mini App | Full JS WebView | Can open own WebSockets |
