# Configuration Reference

Every agent is defined by a single YAML file. All fields except
`name` and `model` are optional with safe defaults.

## Minimal Config

```yaml
name: chat
model:
  provider: claude-code
  api_key_source: keychain
```

This creates a containerized agent with no tools, no file access
beyond `/workspace`, no network beyond `api.anthropic.com`, $1.00
budget, and a 30-minute timeout.

## UI Runtime Config

OpenHORT also reads namespaced server settings from `hort-config.yaml`.
The browser isolation policy controls where llming card JavaScript runs:

```yaml
ui.browser_isolation:
  mode: per_widget        # per_widget | shared_host | auto
  isolate: []             # llming names/globs forced into iframes
  share: []               # llming names/globs allowed in shared host mode
```

| Mode | Effect |
|---|---|
| `per_widget` | Default. Every widget gets its own sandboxed iframe. Safest, slower reloads. |
| `shared_host` | All widget cards load into the host Vue app. Fastest, but reviewed/mutually trusted cards only. |
| `auto` | Simple widgets render in the host; configured, marked, or cross-capability widgets stay isolated. |

In `auto`, use `isolate` for sensitive widgets and `share` for reviewed
widgets you explicitly allow to run in the host page.

## Full Config

```yaml
name: researcher
description: "Research assistant with web access"

# ── Runtime ──────────────────────────────────────────────────────
runtime:
  type: container          # container | local | remote
  image: claude-chat-sandbox:latest
  memory: 1g               # Docker memory limit
  cpus: 2                  # Docker CPU limit
  disk: 5g                 # Docker disk limit (requires xfs+pquota)
  network: restricted      # none | restricted | full
  allowed_hosts:
    - api.anthropic.com
    - api.openai.com

# ── Model ────────────────────────────────────────────────────────
model:
  provider: claude-code    # claude-code | openai | anthropic | llming-model | custom
  name: sonnet
  api_key_source: keychain # keychain | env:VAR_NAME | file:/path
  temperature: 0.7
  max_output_tokens: 4096

# ── Budget ───────────────────────────────────────────────────────
budget:
  max_cost_usd: 5.00
  max_turns: 100
  max_runtime_minutes: 60
  max_tokens: 500000
  warn_at_percent: 80

# ── Permissions ──────────────────────────────────────────────────
permissions:
  tools:
    allow: [Read, Glob, Grep, WebSearch, WebFetch]
    deny: [Edit, Write, Bash]

  mcp_servers:
    allow:
      - sql-generator
      - nice-vibes:
          tools: [get_component_docs, search_topics]
    deny: ["*"]

  commands:
    allow:
      - "^git (status|log|diff|show)"
      - "^python3? .*\\.py$"
    deny:
      - "^rm "
      - "^sudo "

  files:
    - path: /workspace/data
      access: ro
    - path: /workspace/output
      access: rw
    - path: /workspace/secrets
      access: none

  network:
    allow: ["api.anthropic.com:443"]
    deny: ["169.254.169.254", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]

# ── Agent Communication ─────────────────────────────────────────
messaging:
  can_send_to: [coder, reviewer]
  can_receive_from: [orchestrator]
  max_message_size: 32768
  max_messages_per_minute: 30

# ── Access Source Overrides ──────────────────────────────────────
sources:
  local:
    inherit: all
  lan:
    tools:
      allow: [Read, Glob, Grep]
  cloud:
    tools:
      allow: [Read, Glob]
    commands:
      deny: [".*"]
  telegram:
    tools:
      allow: [Read]
    mcp_servers:
      deny: ["*"]

# ── System Prompt ────────────────────────────────────────────────
system_prompt: |
  You are a research assistant. Find information and summarize it.

# ── Hooks ────────────────────────────────────────────────────────
hooks:
  on_start: "echo 'Agent started' >> /workspace/agent.log"
  on_stop: "echo 'Agent stopped' >> /workspace/agent.log"
  on_budget_warning: "notify-send 'Budget warning: {percent}%'"
  on_budget_exceeded: null
```

## Field Reference

### `runtime`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `container` | `container`, `local`, or `remote` |
| `image` | string | `claude-chat-sandbox:latest` | Docker image for container type |
| `memory` | string | unlimited | Memory limit (e.g. `512m`, `2g`) |
| `cpus` | float | unlimited | CPU limit (e.g. `1`, `0.5`, `4`) |
| `disk` | string | unlimited | Disk limit (e.g. `1g`, requires xfs+pquota) |
| `network` | string | `restricted` | `none`, `restricted`, or `full` |
| `allowed_hosts` | list | `[api.anthropic.com]` | Hosts allowed when `network: restricted` |

### `model`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | string | required | `claude-code`, `openai`, `anthropic`, `llming-model`, `custom` |
| `name` | string | provider default | Model name or alias |
| `api_key_source` | string | required | `keychain`, `env:VAR`, `file:/path` |
| `temperature` | float | provider default | Sampling temperature |
| `max_output_tokens` | int | provider default | Max output tokens per turn |

### `budget`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_cost_usd` | float | `1.00` | Maximum API spend per session |
| `max_turns` | int | `50` | Maximum conversation turns |
| `max_runtime_minutes` | int | `30` | Wall-clock timeout |
| `max_tokens` | int | `200000` | Total token budget (in + out) |
| `warn_at_percent` | int | `80` | Warning threshold (%) |

### `permissions`

See [Permissions Reference](../internals/permissions.md).

### `messaging`

See [Multi-Agent Setups](multi-agent.md).

### `sources`

See [Access Sources](../internals/source-policies.md).

### `hooks`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `on_start` | string | null | Shell command run when agent starts |
| `on_stop` | string | null | Shell command run when agent stops |
| `on_budget_warning` | string | null | Run when budget warning threshold is crossed |
| `on_budget_exceeded` | string | null | Run when budget is exceeded (default: kill agent) |

### `node` (multi-node only)

See [Running Across Machines](multi-node.md).
