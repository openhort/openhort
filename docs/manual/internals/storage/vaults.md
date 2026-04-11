# Vaults

A vault is a named storage space within a llming. Each vault has
metadata (group, description) and can contain shelves (scrolls) and
holds (crates).

## Creating Vaults

```python
# Simple vault
main = self.persist.vault("main")

# Vault with metadata
cam = self.persist.vault("security-feeds",
    group="shared",
    description="Live camera frames and motion events",
)

# Private vault (default)
secrets = self.persist.vault("credentials",
    group="private",
    description="API keys and tokens",
)
```

## Vault Groups

| Group | Who can access | Use for |
|-------|---------------|---------|
| `private` | Owner llming only (default) | Credentials, internal state |
| `shared` | Llmings that request + receive permission | Metrics, feeds, processed data |
| `public` | Any llming, no permission needed | Status, heartbeats, public APIs |

## Cross-Llming Access

A llming can request access to another llming's shared vault:

```python
# Request access (returns True if granted)
granted = await self.request_vault_access("llming-cam", "security-feeds")

if granted:
    # Read from the other llming's vault
    frames = await self.remote.vault("llming-cam", "security-feeds") \
                          .shelf("events").find({"motion": True})
```

The owner llming declares who can access via wire rules:

```yaml
llmings:
  llming-cam:
    vaults:
      security-feeds:
        group: shared
        allow: [hort-chief, telegram-connector]
```

Future: permission requests shown as Android-style prompts in the UI.

## Mirroring

Mirror another llming's vault data into your own for unified access:

```python
# Mirror system-monitor's metrics into my own vault
self.persist.mirror(
    source_llming="system-monitor",
    source_vault="metrics",
    into="system-mirror",
)

# Now read locally — same API, no remote calls
cpu = self.persist.vault("system-mirror").shelf("cpu").find_one()
```

Mirrors sync automatically. The source controls access (shared/public
vaults only). Mirror updates arrive via pulses.

## Pulse Routing

Route pulses directly into shelves or holds — auto-insert with
timestamps:

```python
# Every "cpu_load" pulse auto-inserts into the shelf
self.pulse.route("cpu_load",
    into=self.persist.vault("metrics").shelf("history"),
    ttl=86400,  # keep 24h of history
)

# Camera frames routed into hold
self.pulse.route("camera_frame",
    into=self.runtime.vault("feeds").hold("frames"),
    ttl=60,  # keep last 60 seconds
)
```

Each routed pulse becomes a scroll (in a shelf) or a crate (in a hold)
with an automatic `_routed_at` timestamp.

## Unified Pulses

A pulse can carry both a scroll and a crate — structured metadata
alongside binary data:

```python
# Emit a camera frame with metadata
self.pulse.emit("camera_frame", {
    "scroll": {
        "camera_id": "front-door",
        "timestamp": time.time(),
        "motion_detected": True,
        "confidence": 0.92,
    },
    "crate": {
        "name": "frame.webp",
        "data": webp_bytes,
        "content_type": "image/webp",
    },
})
```

Subscribers receive both parts. When routed into storage, the scroll
goes to a shelf and the crate goes to a hold — automatically.

## Peeking

Check what pulses are available without subscribing:

```python
# List all pulses I can see (respects access levels)
available = self.pulse.available()
# [{"llming": "system-monitor", "name": "cpu_load", "group": "public"},
#  {"llming": "llming-cam", "name": "camera_frame", "group": "shared"}]

# Am I subscribed to this pulse?
if self.pulse.subscribed("llming-cam", "camera_frame"):
    ...

# Peek at the latest value without subscribing
latest = self.pulse.peek("system-monitor", "cpu_load")
# {"cpu": 42.5, "_ts": 1775900000}
```

## Full Hierarchy

```
Llming
  └── persist / runtime
       └── vault("name", group="shared", description="...")
            ├── shelf("collection")     ← scrolls (JSON records)
            │    ├── scroll             ← one record
            │    └── scope("filter")    ← filtered view
            └── hold("container")       ← crates (binary objects)
                 └── crate              ← one binary object
```
