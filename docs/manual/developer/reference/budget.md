# Budget Limits

Budget is tracked on the HOST, not by the agent. The agent cannot
lie about costs — the framework parses stream-json output and
extracts real usage data.

## Configuration

```yaml
budget:
  max_cost_usd: 5.00         # API spend cap
  max_turns: 100              # conversation turn cap
  max_runtime_minutes: 60     # wall-clock timeout
  max_tokens: 500000          # total tokens (in + out)
  warn_at_percent: 80         # warning threshold
```

All limits are optional. Defaults:

| Limit | Default |
|-------|---------|
| `max_cost_usd` | `1.00` |
| `max_turns` | `50` |
| `max_runtime_minutes` | `30` |
| `max_tokens` | `200000` |
| `warn_at_percent` | `80` |

## When Limits Are Checked

1. **Before each turn** — if any limit is already exceeded,
   the turn is refused
2. **After each turn** — counters are updated from the `result`
   event's `usage` and `total_cost_usd` fields

## What Happens When a Limit Is Hit

1. The current turn completes (not killed mid-response)
2. A budget-exceeded message is printed
3. The `on_budget_exceeded` hook runs (if configured)
4. Further turns are refused until the session restarts

## Warning Hooks

When any counter crosses `warn_at_percent` of its limit:

```yaml
hooks:
  on_budget_warning: "notify-send 'Budget: {percent}%'"
  on_budget_exceeded: null   # default: just stop
```

## Multi-Node Budget

In multi-node setups, the worker enforces its own cap independently:

```yaml
# In node.yaml on the worker
max_budget_usd_per_session: 5.00
```

The effective limit is the LOWER of the agent's configured budget
and the worker's per-session cap. A controller cannot override
a worker's local budget limit.
