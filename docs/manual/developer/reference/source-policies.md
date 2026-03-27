# Access Source Policies

Permissions depend on WHERE a request comes from. A tool that's
safe at the keyboard is dangerous when triggered via Telegram.

## Access Sources

| Source | Identifier | Detection |
|--------|-----------|-----------|
| Local terminal | `local` | stdin is a TTY, process runs on host |
| Local web UI | `lan` | Request from LAN IP (192.168.x.x, 10.x.x.x) |
| Remote web UI | `cloud` | Routed through access server tunnel |
| Telegram | `telegram` | Message via Telegram connector |
| Another agent | `agent:<name>` | Message via message bus |
| Scheduled job | `scheduler` | Triggered by timer |
| REST API | `api` | Bearer token on REST endpoint |

## Source-Scoped Permissions

The `sources` section restricts permissions per access source.
Source overrides INTERSECT with base permissions — they can only
reduce what's allowed, never add.

```yaml
permissions:
  tools:
    allow: [Read, Write, Edit, Bash, Glob, Grep]
  commands:
    allow: ["^python3 ", "^git ", "^docker "]

sources:
  local:
    inherit: all              # full access at the keyboard

  lan:
    tools:
      allow: [Read, Glob, Grep, Bash]
    commands:
      allow: ["^python3 ", "^git (status|log|diff)"]
      deny: ["^docker "]

  cloud:
    tools:
      allow: [Read, Glob, Grep]
    commands:
      deny: [".*"]            # no shell at all

  telegram:
    tools:
      allow: [Read]
    mcp_servers:
      deny: ["*"]

  agent:orchestrator:
    inherit: all              # full trust from orchestrator

  agent:*:
    tools:
      allow: [Read, Glob, Grep]   # read-only for unknown agents

  scheduler:
    tools:
      allow: [Bash, Read]
    commands:
      allow: ["^python3 scripts/daily_report\\.py$"]
      deny: [".*"]
```

## Resolution

1. Find the most specific source match (exact > wildcard)
2. If no match → **DENY ALL** (fail-closed)
3. If `inherit: all` → use base permissions
4. Otherwise → intersect base and override (only allow what BOTH permit)

!!! warning "Unlisted sources are denied"
    If a source is not in your `sources` section, it gets zero
    access. You must list every source you want to support.

## Default Policy

If no `sources` section is provided, this default applies:

```
                    local   lan   cloud   telegram   agent   scheduler   api
Read-only tools      yes    yes    yes      yes       yes      yes       yes
Write tools          yes    yes     -        -         *        -         -
Bash                 yes     -      -        -         *        *         -
MCP servers          yes    yes     -        -         *        -         -
Agent messaging      yes    yes    yes      yes       yes      yes        -
File mounts (rw)     yes    yes     -        -         -        -         -
Agent start/stop     yes    yes     -        -         -        -        yes

* = only if explicitly granted
```

## Source Detection

The access source is determined at the system edge and attached
as an immutable `RequestContext`. Container-originated requests
are always tagged as `agent:<name>` — they cannot impersonate
`local` or `lan` sources.
