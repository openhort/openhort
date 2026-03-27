# Multi-Agent Setups

Agents communicate through a central message bus on the host.
No direct container-to-container networking — every message is
inspected, permission-checked, rate-limited, and audit-logged.

## Messaging Configuration

```yaml
messaging:
  can_send_to: [coder, reviewer]
  can_receive_from: [orchestrator]
  max_message_size: 32768       # bytes, default 32KB
  max_messages_per_minute: 30   # rate limit per agent
```

Both sides must agree: the sender must list the recipient in
`can_send_to`, AND the recipient must list the sender in
`can_receive_from`. If either side is missing, the message
is rejected.

## How Messages Flow

Agents send messages via a built-in MCP tool:

```json
{
  "name": "send_message",
  "input_schema": {
    "properties": {
      "to": {"type": "string"},
      "content": {"type": "string"},
      "type": {"enum": ["task", "result", "status", "error"]}
    }
  }
}
```

Incoming messages are injected into the agent's context on the
next turn.

## Topologies

### Pipeline (A then B then C)

```yaml
# agent-a.yaml
messaging:
  can_send_to: [agent-b]

# agent-b.yaml
messaging:
  can_receive_from: [agent-a]
  can_send_to: [agent-c]

# agent-c.yaml
messaging:
  can_receive_from: [agent-b]
```

### Hub and Spoke (orchestrator + workers)

```yaml
# orchestrator.yaml
messaging:
  can_send_to: [worker-1, worker-2, worker-3]
  can_receive_from: [worker-1, worker-2, worker-3]

# Each worker
messaging:
  can_send_to: [orchestrator]
  can_receive_from: [orchestrator]
```

### Peer Review (two agents review each other)

```yaml
# coder.yaml
messaging:
  can_send_to: [reviewer]
  can_receive_from: [reviewer]

# reviewer.yaml
messaging:
  can_send_to: [coder]
  can_receive_from: [coder]
```

## Full Example: Research + Code Pipeline

```yaml
# agents/orchestrator.yaml
name: orchestrator
model:
  provider: claude-code
  name: opus
  api_key_source: keychain
budget:
  max_cost_usd: 10.00
permissions:
  tools:
    allow: [Read, Glob, Grep]
messaging:
  can_send_to: [researcher, coder, reviewer]
  can_receive_from: [researcher, coder, reviewer]
system_prompt: |
  You coordinate a team. Send research tasks to "researcher",
  coding tasks to "coder", and review requests to "reviewer".

---
# agents/researcher.yaml
name: researcher
model: { provider: claude-code, name: sonnet, api_key_source: keychain }
budget: { max_cost_usd: 2.00 }
permissions:
  tools: { allow: [Read, Glob, Grep, WebSearch, WebFetch] }
messaging:
  can_send_to: [orchestrator]
  can_receive_from: [orchestrator]

---
# agents/coder.yaml
name: coder
model: { provider: claude-code, name: sonnet, api_key_source: keychain }
budget: { max_cost_usd: 3.00 }
permissions:
  tools: { allow: [Read, Write, Edit, Bash, Glob, Grep] }
  commands:
    allow: ["^python3 ", "^git (status|diff|add|commit)"]
    deny: ["^rm ", "^curl "]
messaging:
  can_send_to: [orchestrator]
  can_receive_from: [orchestrator]

---
# agents/reviewer.yaml
name: reviewer
model: { provider: claude-code, name: opus, api_key_source: keychain }
budget: { max_cost_usd: 2.00 }
permissions:
  tools: { allow: [Read, Glob, Grep] }
messaging:
  can_send_to: [orchestrator, coder]
  can_receive_from: [orchestrator]
```

Launch all at once:

```bash
poetry run hort agent start agents/orchestrator.yaml \
                          agents/researcher.yaml \
                          agents/coder.yaml \
                          agents/reviewer.yaml
```

## Loop Protection

Message amplification (A sends to B, B sends back to A, repeat)
is prevented by:

- Rate limits (`max_messages_per_minute`)
- Correlation ID tracking — if the same correlation ID appears
  more than 10 times, it's blocked
- Each message counts against the sending agent's turn budget
