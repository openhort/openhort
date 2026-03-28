# Screen Capture Architecture

How openhort captures windows and the full desktop on macOS.

## Capture Modes

### Per-Window Capture

Uses `CGWindowListCreateImage` with `kCGWindowListOptionIncludingWindow`
to capture a single window by its window ID.

```python
capture_window(window_id=12345, max_width=800, quality=70)
```

### Full Desktop Capture

Uses `CGDisplayCreateImage(CGMainDisplayID())` to capture the
entire main display — all windows composited, like TeamViewer
or Remote Desktop.

```python
from hort.screen import DESKTOP_WINDOW_ID
capture_window(window_id=DESKTOP_WINDOW_ID, max_width=800, quality=70)
```

`DESKTOP_WINDOW_ID = -1` is a magic constant. When passed to
`capture_window()`, it routes to `_raw_capture_desktop()` instead
of `_raw_capture()`.

## Virtual Desktop Entry

`hort/windows.py` prepends a virtual "Desktop — Full Screen" entry
to the window list (window_id=-1). It appears as the first card in
the picker grid.

```python
WindowInfo(
    window_id=DESKTOP_WINDOW_ID,  # -1
    owner_name="Desktop",
    window_name="Full Screen",
    bounds=WindowBounds(x=0, y=0, width=screen_w, height=screen_h),
    owner_pid=0,  # no specific app
)
```

**Bounds** come from `CGDisplayBounds(CGMainDisplayID())` — the
actual logical pixel dimensions of the main display. These must
match the captured image dimensions for click coordinate mapping.

## Input in Desktop Mode

When clicking in the Desktop viewer:
- `owner_pid=0` → `_activate_app()` is skipped (no app to raise)
- Click goes to absolute screen coordinates via `CGEventPost`
- macOS delivers the click to whatever window is at those coordinates

The stream also skips `_raise_window()` for Desktop (window_id < 0).

## Thumbnail Rotation (`hort/thumbnailer.py`)

Instead of the client requesting all thumbnails simultaneously
(N concurrent Quartz captures), the server maintains a rotation
queue.

### How it works

1. Client sends `subscribe_thumbnails` once (instead of N `get_thumbnail` requests)
2. Server cycles through all windows, capturing one at a time
3. Each thumbnail is pushed to all subscribed clients
4. Rate: ~2 captures/second, regardless of window count

### Timing

| Windows | Cycle time | Per-window refresh |
|---------|-----------|-------------------|
| 5 | 2.5s | every 2.5s |
| 10 | 5s | every 5s |
| 30 | 15s | every 15s |
| 50 | 15s (capped) | every 15s |

Constants:
```python
MIN_INTERVAL = 0.5    # fastest: 2 captures/sec
MAX_CYCLE_TIME = 15.0 # full rotation capped at 15s
THUMB_MAX_WIDTH = 400  # smaller than stream (400 vs 800)
THUMB_QUALITY = 40     # lower quality for thumbs
```

### Memory

- At most 1 CGImage in memory at a time (sequential captures)
- Cached thumbnails stored as base64 strings (~20-50 KB each)
- Old cache entries removed when windows disappear

### Client Integration

```javascript
// Old (N concurrent captures — DO NOT USE):
state.navWindows.forEach(w => requestThumbnail(w.window_id));

// New (server-side rotation):
subscribeThumbnails();
```

## Stream Backpressure (`hort/stream.py`)

The binary stream WebSocket uses a `maxsize=1` asyncio Queue to
prevent memory growth when the client can't keep up:

```python
_frame_queue = asyncio.Queue(maxsize=1)

# Capture loop (producer):
if _frame_queue.full():
    _frame_queue.get_nowait()  # drop old frame
_frame_queue.put_nowait(frame)

# Send loop (consumer):
frame = await _frame_queue.get()
await websocket.send_bytes(frame)
```

At most 1 frame is buffered. If the client is slow (proxy, slow
network), frames are dropped — the viewer gets a lower effective
FPS but memory stays flat.

## Mobile Keyboard

On touch devices, the viewer toolbar shows a keyboard icon.
Tapping it focuses a hidden `<input>` element that triggers the
on-screen keyboard. Key input is forwarded as `input` events to
the remote machine.

Hidden on desktop (detected via `@media (hover: hover) and (pointer: fine)`).

## Future: ScreenCaptureKit Migration

`CGWindowListCreateImage` is deprecated in macOS 15 SDK (still
works at runtime through macOS 26). The modern replacement is
ScreenCaptureKit (`SCScreenshotManager`, macOS 14+).

Benefits:
- System permission asked once (not per-window)
- Buffer pool management (better memory for streaming)
- HDR capture support (macOS 15+)

Complexity:
- All APIs are async with completion handlers
- pyobjc has no `await` bridge yet (must use threading)
- `SCScreenshotManager` requires macOS 14+ (Sonoma)

On the roadmap for Phase 4. See `docs/manual/developer/internals/roadmap.md`.
