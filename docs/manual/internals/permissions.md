# Permissions Reference

The permission system controls what an agent can do. Everything
is deny-by-default — an agent has zero access unless explicitly
granted.

## Tool Permissions

```yaml
permissions:
  tools:
    allow: [Read, Glob, Grep]
    deny: [Bash, Edit, Write]
```

**Resolution order:**

1. If tool is in `deny` → BLOCKED (deny always wins)
2. If tool is in `allow` → PERMITTED
3. If neither → BLOCKED (deny-by-default)

Use `"*"` as a wildcard to match all tools.

For Claude Code CLI, this maps to `--allowedTools` and
`--disallowedTools` flags. For API-based providers, tools are
filtered before being sent in the request — the model never
sees tools it can't use.

## MCP Server Permissions

```yaml
permissions:
  mcp_servers:
    allow:
      - sql-generator              # all tools
      - nice-vibes:                # only specific tools
          tools:
            - get_component_docs
            - search_topics
    deny:
      - "*"                        # deny all not listed
```

The agent launcher builds a filtered MCP config that only
includes allowed servers. For scoped access, a proxy intercepts
`tools/list` and `tools/call` to enforce the subset.

## Command Filtering

When the Bash tool is allowed, every command is checked against
regex patterns before execution.

```yaml
permissions:
  commands:
    allow:
      - "^git (status|log|diff|show)"
      - "^python3? .*\\.py$"
    deny:
      - "^rm "
      - "^sudo "
      - "^curl.*(-d|--data)"
      - ".*\\|.*sh$"
```

**Resolution order:**

1. Match against hardcoded deny list (always checked, not overridable)
2. Match against your `deny` patterns → BLOCKED
3. Match against your `allow` patterns → PERMITTED
4. No match → BLOCKED

The filter runs on the HOST, not inside the container. The agent
cannot bypass it — all commands flow through `claude -p` stream-json
events which the framework intercepts.

??? note "Hardcoded deny patterns (always active)"
    These patterns cannot be overridden in YAML:

    - `rm -r` / `rm -R` / `rm --no-preserve-root`
    - Redirect to devices (`> /dev/sda`)
    - `mkfs`, `dd of=/dev/`
    - `reboot`, `shutdown`, `halt`, `poweroff`
    - `sudo`, `su`
    - `curl | sh`, `wget | sh`
    - World-writable chmod on root paths

## File Access Control

```yaml
permissions:
  files:
    - path: /workspace/data
      access: ro           # read-only
    - path: /workspace/output
      access: rw           # read-write
    - path: /workspace/secrets
      access: none         # not mounted at all
```

| Access | Docker mount | Effect |
|--------|-------------|--------|
| `ro` | `-v path:path:ro` | Read-only bind mount |
| `rw` | `-v path:path` | Read-write bind mount |
| `none` | Not mounted | Path does not exist in container |

Default mounts (always present):

- `/workspace` (rw) — agent working directory
- `/home/claude/.claude` (rw) — session persistence

## Network Permissions

```yaml
permissions:
  network:
    allow:
      - "api.anthropic.com:443"
    deny:
      - "169.254.169.254"     # cloud metadata
      - "10.0.0.0/8"          # private networks
```

Also controlled at the `runtime` level:

```yaml
runtime:
  network: restricted         # none | restricted | full
  allowed_hosts:
    - api.anthropic.com
```

| Level | Implementation |
|-------|---------------|
| `none` | `docker run --network none` — completely air-gapped |
| `restricted` | Docker network with iptables allowlist |
| `full` | Default Docker networking (not recommended) |
