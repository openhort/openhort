# Multi-Instance Isolation

Multiple openhort instances can run on the same machine (e.g. dev + production,
or multiple users). Each instance is fully isolated — they share nothing.

## Configuration

Set `HORT_INSTANCE_NAME` in each instance's `.env`:

```bash
# Instance A (.env)
HORT_INSTANCE_NAME=production
HORT_HTTP_PORT=8940

# Instance B (.env)
HORT_INSTANCE_NAME=dev
HORT_HTTP_PORT=8941
```

When `HORT_INSTANCE_NAME` is set, all data is stored under
`~/.hort/instances/{name}/`. Without it, data goes to `~/.hort/` (single-instance
default, backward compatible).

## Data Directory Layout

```
~/.hort/
├── instances/
│   ├── production/
│   │   ├── plugins/              # Per-llming key-value stores + files
│   │   │   ├── hue-bridge.data/  # Hue API key, bridge IP
│   │   │   ├── llming-wire.data/ # Chat conversations
│   │   │   └── ...
│   │   ├── tokens.json           # Cloud access tokens
│   │   ├── hortmap/              # Circuits/flow editor data
│   │   └── current-temp-token    # Temporary cloud session token
│   └── dev/
│       ├── plugins/
│       ├── tokens.json
│       └── ...
├── statusbar.key                 # Shared: macOS status bar IPC (not namespaced)
└── plugins/                      # Legacy: used when HORT_INSTANCE_NAME is unset
```

## What Is Isolated

| Resource | Namespaced | Path |
|----------|-----------|------|
| Plugin data stores | Yes | `~/.hort/instances/{name}/plugins/{id}.data/` |
| Plugin file stores | Yes | `~/.hort/instances/{name}/plugins/{id}.files/` |
| Cloud access tokens | Yes | `~/.hort/instances/{name}/tokens.json` |
| Temporary cloud token | Yes | `~/.hort/instances/{name}/current-temp-token` |
| Hortmap flows | Yes | `~/.hort/instances/{name}/hortmap/` |
| HTTP port | Yes | `HORT_HTTP_PORT` env var |
| HTTPS port | Yes | `HORT_HTTPS_PORT` env var |
| P2P relay room | Yes | SHA-256 of bot token (unique per `TELEGRAM_BOT_TOKEN`) |
| P2P data channel proxy | Yes | Reads `HORT_HTTP_PORT` to target correct local port |
| macOS status bar key | **No** | `~/.hort/statusbar.key` (shared IPC, intentional) |

## Implementation

All data paths are resolved through a single helper:

```python
from hort.hort_config import hort_data_dir

data_dir = hort_data_dir()
# With HORT_INSTANCE_NAME=dev → ~/.hort/instances/dev/
# Without HORT_INSTANCE_NAME   → ~/.hort/
```

!!! warning "Never hardcode `~/.hort/` paths"
    All code that reads or writes instance-specific data must use
    `hort_data_dir()`. Hardcoding `~/.hort/plugins` or similar paths causes
    cross-instance data corruption when multiple instances run on the same
    machine.

### Files Using `hort_data_dir()`

| File | What it stores |
|------|---------------|
| `hort/ext/store.py` | Plugin key-value data (PluginStore) |
| `hort/ext/file_store.py` | Plugin binary files (PluginFileStore) |
| `hort/ext/registry.py` | Plugin store injection during loading |
| `hort/llming/registry.py` | Llming store injection during loading |
| `hort/access/tokens.py` | Cloud access token store |
| `hort/hortmap/store.py` | Circuits/flow editor data |
| `hort/app.py` | Temporary cloud session token file |

### Exception: Status Bar Key

The macOS status bar key (`~/.hort/statusbar.key`) is intentionally **not**
namespaced. It's an IPC mechanism between the openhort server and the native
status bar app — both need to find it at a known shared path regardless of
instance name.

## P2P Isolation

Each instance has its own P2P relay room, derived from its unique
`TELEGRAM_BOT_TOKEN`. Even if two instances run on the same machine, their relay
rooms never overlap.

After WebRTC signaling completes, the `DataChannelProxy` proxies HTTP/WS traffic
to the local server. It reads `HORT_HTTP_PORT` from the environment to target
the correct port — never hardcoded.

See [Peer-to-Peer: Multi-Instance Isolation](peer2peer.md#multi-instance-isolation)
for the full security analysis.

!!! info "Historical bug (fixed 2026-04-11)"
    The `DataChannelProxy` previously hardcoded port 8940, causing all P2P
    traffic to route to port 8940 regardless of which instance handled the
    signaling. This was fixed by reading `HORT_HTTP_PORT` from the environment.

## Migration

Existing single-instance installations continue to work without changes.
Setting `HORT_INSTANCE_NAME` for the first time creates a new empty data
directory. To migrate existing data:

```bash
# Copy existing data to the new instance directory
cp -r ~/.hort/plugins ~/.hort/instances/myinstance/plugins
cp ~/.hort/tokens.json ~/.hort/instances/myinstance/tokens.json
```
