# Circuit Error Handling

Production flows must handle failures gracefully. Currently a
failing node in a Circuit has no defined behavior.

## Per-node error policy

Each node should have a configurable error strategy:
- **Stop** — halt the Circuit (default, current behavior)
- **Retry** — retry N times with exponential backoff
- **Fallback** — route to an error output path
- **Ignore** — log and continue to next node
- **Notify** — send error notification (Telegram, log) and stop

## Error output

Nodes with error handling get a second output (error path):

```
[Fetch email] ──success──→ [Process]
      │
      └──error──→ [Notify admin] → [Log to file]
```

## Circuit-level policies

Default error strategy for all nodes in a Circuit:
- Timeout per node (e.g. 30 seconds)
- Max retries (e.g. 3)
- Circuit-level timeout (e.g. 5 minutes)
- Dead letter queue for failed signals

## Priority

Important for production use. Toy Circuits can skip this,
but anything running unattended needs error handling.
