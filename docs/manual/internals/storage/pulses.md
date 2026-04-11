# Pulses

Live state and events — the third data system. Unlike scrolls and
crates, pulses are ephemeral: in-memory only, never persisted, real-time.

## Two Concepts

| Concept | What | Persistence | Example |
|---------|------|-------------|---------|
| **State** | Current value, readable anytime | In-memory (latest only) | CPU: 42%, camera: active |
| **Event** | Something happened, subscribable | None (fire and forget) | Screenshot taken, email received |

## API (from a llming)

### Publishing

```python
# Publish current state (replaces previous value)
def get_pulse(self) -> dict:
    return {
        "cpu": self._cpu,
        "memory_mb": self._mem,
        "uptime_s": time.monotonic() - self._start,
    }

# Emit an event
self.pulse.emit("screenshot_taken", {
    "path": "/tmp/screenshot.png",
    "width": 3440, "height": 1440,
}, access="public")
```

### Subscribing

```python
# Read another llming's current state
cpu = await self.pulse.read("system-monitor", "cpu")

# Subscribe to events
async def on_screenshot(data):
    print(f"Screenshot: {data['width']}x{data['height']}")

self.pulse.subscribe("screenshot-capture", "screenshot_taken", on_screenshot)
```

## Access Levels

Pulses follow the same access model as scrolls and crates:

| Level | Who reads | Example |
|-------|----------|---------|
| `private` | Owner only | Internal timers, debug counters |
| `shared` | Permitted llmings | Process list, email count |
| `public` | Anyone | CPU, memory, camera count, disk space |

```python
# In get_pulse — the framework tags each field
def get_pulse(self) -> dict:
    return {
        "cpu": 42.5,           # access declared in manifest
        "process_count": 128,   # access declared in manifest
    }
```

Access levels for pulse fields are declared in the manifest:

```json
{
  "pulse": {
    "fields": {
      "cpu": {"access": "public"},
      "memory_mb": {"access": "public"},
      "process_list": {"access": "shared"},
      "internal_state": {"access": "private"}
    }
  }
}
```

## How Pulses Differ from Scrolls

| | Scrolls | Pulses |
|---|---|---|
| Persisted | Yes (SQLite) | No (in-memory) |
| Queryable | Yes (filters, sort) | No (read current value) |
| Historical | Yes (all versions) | No (latest only) |
| TTL | Yes | N/A (always latest) |
| Cross-restart | Yes (persist) or No (runtime) | No (always lost) |
| Use case | Data that matters | Status that's live |

## Under the Hood

- `PulseBus` singleton manages all state and subscriptions
- State is a `dict` per llming, updated on each `get_pulse()` call
- Events broadcast to subscribers via `asyncio.Queue`
- Zero persistence — pulses exist only while the server runs
- Subscribers can be other llmings, the UI (via WS), or connectors
