# Wire Protocol Reference

Technical details of the streaming protocol, message formats,
and inter-node communication.

## Stream-JSON Protocol

Claude CLI with `--output-format stream-json --verbose --include-partial-messages`
emits one JSON object per line on stdout.

### Events We Consume

**Init** — first event, provides session ID:
```json
{"type": "system", "subtype": "init", "session_id": "uuid", "tools": [...], "model": "..."}
```

**Text delta** — incremental response fragment:
```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_delta",
    "index": 0,
    "delta": {"type": "text_delta", "text": "Hello"}
  }
}
```

**Result** — final event with cost and usage:
```json
{
  "type": "result",
  "subtype": "success",
  "session_id": "uuid",
  "total_cost_usd": 0.037,
  "result": "full response text",
  "usage": {"input_tokens": 100, "output_tokens": 50}
}
```

### Events We Skip

| Event | Why |
|-------|-----|
| `thinking_delta` | Internal reasoning, not shown |
| `signature_delta` | Thinking block signature |
| `message_start/stop` | Lifecycle markers |
| `content_block_start/stop` | Block boundaries |
| `assistant` | Full snapshot (redundant with deltas) |
| `rate_limit_event` | Not user-facing |

### Error Handling

- Malformed JSON lines: silently skipped
- Empty lines: silently skipped
- Missing session ID in init: extracted from result as fallback
- No text events: typewriter prints "(no response)"

## Agent Message Format

```python
@dataclass(frozen=True)
class AgentMessage:
    from_agent: str          # "researcher" or "researcher@pi-workshop"
    to_agent: str
    content: str
    message_type: str        # "task" | "result" | "status" | "error"
    correlation_id: str      # links request to response
    timestamp: float
    metadata: dict
```

## Tunnel Protocol (Multi-Node)

Controller-to-worker communication uses JSON over WebSocket.

**Controller to worker:**
```json
{"type": "agent_start", "req_id": "r1", "agent_config": { ... }}
{"type": "agent_stop", "req_id": "r2", "agent_name": "researcher"}
{"type": "agent_status", "req_id": "r3"}
{"type": "agent_message", "req_id": "r4", "to_agent": "researcher", "message": { ... }}
```

**Worker to controller:**
```json
{"type": "response", "req_id": "r1", "status": "ok", "data": { ... }}
{"type": "agent_event", "agent_name": "researcher", "event": "budget_warning", "data": { ... }}
{"type": "heartbeat", "agents": [{"name": "researcher", "status": "running", "budget_pct": 42}]}
```

Heartbeats are sent every 30 seconds. If missing for 90 seconds,
the node is marked offline.

## Typewriter Display

The typewriter engine smooths output into consistent streaming:

| Buffer depth | Speed | Chunk size |
|-------------|-------|------------|
| < 20 chars | 300 cps | 1 char |
| 20-80 chars | 300-4000 cps | 1 char |
| 80+ chars | 4000 cps | multi-char |

After the stream ends, remaining buffer is flushed within 2 seconds
using dynamically-sized chunks.

## Audit Log Format

JSONL, one event per line:

```json
{"ts": "2026-03-26T10:15:00Z", "agent": "researcher", "event": "tool_call", "tool": "Read", "args": {"file_path": "/workspace/data.csv"}, "result": "allowed"}
{"ts": "2026-03-26T10:15:01Z", "agent": "researcher", "event": "command_blocked", "command": "rm -rf /", "rule": "hardcoded_deny"}
{"ts": "2026-03-26T10:15:02Z", "agent": "researcher", "event": "budget_update", "cost_usd": 0.12, "turns": 3, "cost_pct": 2.4}
```

Storage: `~/.hort/agent-audit/{agent-name}/{date}.jsonl`, retained
90 days, not mounted into any container.
