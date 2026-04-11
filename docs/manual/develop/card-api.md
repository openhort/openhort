# Card API

JS cards interact with llmings through the Card API — a set of WS
commands that provide the same capabilities as Python llmings:
pulse subscriptions, vault access, and power execution.

## Pulse Subscriptions (Push-Only)

Cards subscribe to named pulse channels. When a llming emits on that
channel, the server pushes the event to all subscribed viewers.

```javascript
class SystemMonitorCard extends LlmingClient {
    static id = 'system-monitor';

    onConnect() {
        // Subscribe to pulse channel — server pushes events
        this.subscribe('system_metrics', (data) => {
            this._cpu = data.cpu_percent;
            this._mem = data.mem_percent;
        });
    }
}
```

Pulses can **never be read**. You subscribe and receive events, or
you miss them. For persistent data, use vaults.

## Vault Access

Read and write key-value data. Own vault by default, other llmings'
vaults with the `owner` parameter (if permitted by manifest).

```javascript
// Read from own vault
const data = await this.vaultRead('latest_metrics');

// Read from another llming's vault
const diskData = await this.vaultRead('latest', 'disk-usage');

// Write to own vault
await this.vaultWrite('user_prefs', { theme: 'dark' });
```

## Power Execution

Execute powers on own llming or other llmings (if permitted).

```javascript
// Execute own power
const result = await this.call('get_metrics');

// Execute another llming's power
const lights = await this.call('list_lights', {}, 'hue-bridge');
```

## Scrolls Queries

Query document collections in a llming's storage.

```javascript
// Query own scrolls
const history = await this.scrollsQuery('metrics_history', { cpu: { $gt: 90 } });

// Query another llming's scrolls
const events = await this.scrollsQuery('events', {}, { owner: 'alert-manager', limit: 20 });
```

## Initial Data on Connect

Cards should load initial data in `onConnect()` — this fires when
the WS connects (or when the card script loads after connection).

```javascript
onConnect() {
    // Subscribe to live updates
    this.subscribe('disk_usage', (data) => {
        this._partitions = data.partitions;
    });

    // Load initial data from vault (persisted from last poll)
    this.vaultRead('latest').then(data => {
        if (data && data.partitions) {
            this._partitions = data.partitions;
        }
    });
}
```

## WS Message Types

All Card API messages go through the control WebSocket:

| Message Type | Direction | Purpose |
|---|---|---|
| `card.subscribe` | Client → Server | Subscribe to pulse channel |
| `card.unsubscribe` | Client → Server | Unsubscribe from channel |
| `card.vault.read` | Client → Server | Read from vault |
| `card.vault.write` | Client → Server | Write to own vault |
| `card.power` | Client → Server | Execute a power |
| `card.scrolls.query` | Client → Server | Query scrolls collection |
| `pulse` | Server → Client | Pushed pulse event |

## Permissions

Manifest declares what a llming's cards can access:

```json
{
    "name": "dashboard",
    "reads_vaults": ["system-monitor", "disk-usage"],
    "subscribes": ["system_metrics", "disk_usage"]
}
```

Cards always have full access to their own llming's vaults and powers.
