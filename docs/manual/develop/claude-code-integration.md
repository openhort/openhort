# Claude Code Integration

How Claude Code runs as a standard llming with sandboxed container execution (envoy), cross-platform credential management, and unified routing across all connectors.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ 🏠 Host (macOS / Linux / Windows)                       │
│                                                          │
│  📦 telegram ──┐                                         │
│  📦 wire ──────┤──→ 📦 claude-code (llming)              │
│  📦 any ───────┘       │ Soul (system prompt)            │
│                        │ Powers (send_message, etc.)     │
│                        │ Cards (chat panel)              │
│                        │ credentials (keychain/env)      │
│                        │                                 │
│                        ↓                                 │
│               ┌─────────────────┐                        │
│               │ ChatBackendMgr  │                        │
│               │  MCP bridge     │──→ SSE server          │
│               │  system prompt  │    (host.docker.       │
│               │  session mgmt   │     internal:PORT)     │
│               └────────┬────────┘                        │
│                        │                                 │
│  ┌─────────────────────┼────────────────────────────┐    │
│  │ 🏠 Container (envoy)│                             │    │
│  │                     ↓                             │    │
│  │  claude -p --bare --settings /workspace/.claude/  │    │
│  │    --mcp-config /workspace/.claude-mcp.json       │    │
│  │    --output-format stream-json                    │    │
│  │    "user message"                                 │    │
│  │                                                   │    │
│  │  /workspace/.claude/api_key  ← OAuth token        │    │
│  │  /workspace/.claude/settings.json ← apiKeyHelper  │    │
│  │  /workspace/.claude-mcp.json ← MCP server config  │    │
│  └───────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## YAML Configuration

```yaml
llmings:
  claude:
    type: openhort/claude-code
    config:
      model: claude-sonnet-4-6
      credentials: keychain
    envoy:
      container:
        image: openhort-claude-code
        memory: 2g
        cpus: 2
```

- `config.model` — Claude model override (default: Claude's own default)
- `config.credentials` — `keychain` (OS credential store) or `env` (ANTHROPIC_API_KEY)
- `envoy.container` — defines the sub-hort; presence of `envoy` enables container mode

## Credential Flow

### Cross-Platform OS Credential Store

| OS | Store | How |
|---|---|---|
| **macOS** | Keychain | `security find-generic-password -s "Claude Code-credentials"` |
| **Linux** | libsecret | `secret-tool lookup service "Claude Code-credentials"` |
| **Windows** | Credential Manager | PowerShell `Get-StoredCredential` |

The credential JSON contains OAuth tokens:

```json
{
  "claudeAiOauth": {
    "accessToken": "sk-ant-oat01-...",
    "refreshToken": "sk-ant-ort01-...",
    "expiresAt": 1775656655494
  }
}
```

### Injection into Container

The container filesystem is read-only (`/home/sandbox`). Credentials are written to `/workspace` (the writable volume):

1. Host extracts OAuth token from OS credential store (or `ANTHROPIC_API_KEY`)
2. Writes `/workspace/.claude/api_key` (the raw token)
3. Writes `/workspace/.claude/settings.json` with `apiKeyHelper`
4. Claude CLI reads token via: `--settings /workspace/.claude/settings.json` → `apiKeyHelper: "cat /workspace/.claude/api_key"`

`HOME=/workspace` is set via `docker exec -e` so Claude finds `~/.claude.json` at `/workspace/.claude.json`.

Credentials are:
- Never in container environment (`docker inspect` shows nothing)
- Never in process arguments (`ps aux` shows nothing)
- Re-provisioned on container reuse (handles token refresh)

### Fallback Chain

```
1. ANTHROPIC_API_KEY env var → direct API key
2. OS credential store → OAuth access token
3. Neither → RuntimeError (no credentials)
```

## Container Lifecycle

### Persistent Sub-Horts

Containers are long-lived — they persist across server restarts:

1. **First chat message** → create container, provision credentials, cache
2. **Subsequent messages** → reuse cached container (same process)
3. **Server restart** → scan `ohsb-*` containers, find matching image, reuse
4. **Image change** → create new container (old one orphaned)

### Reuse Strategy

```
1. In-memory cache hit? → health check → reuse
2. Find by label (claude:<image>) → reuse + re-provision credentials
3. Find by image match → claim orphan + re-provision
4. Nothing found → create new
```

One container per image, shared across all chat sessions (Telegram, Wire, etc.). The container is the envoy — not per-user.

### Container Security (7 Layers)

1. Non-root user (UID 1000 `sandbox`)
2. Capabilities: `--cap-drop ALL --cap-add NET_BIND_SERVICE`
3. Seccomp: custom syscall allowlist
4. `--security-opt=no-new-privileges`
5. Network: metadata endpoint blocked, private ranges denied
6. Resources: memory limit, CPU limit, PID limit (256)
7. Read-only root filesystem (`/workspace` + `/tmp` writable)

## Claude CLI Flags

```bash
claude -p                          # prompt mode (non-interactive)
  --output-format stream-json      # streaming JSON output
  --verbose                        # include tool use details
  --bare                           # minimal mode: no keychain, no hooks
  --settings /workspace/.claude/settings.json  # auth via apiKeyHelper
  --mcp-config /workspace/.claude-mcp.json     # MCP server config
  --allowedTools Bash,Read,Write,Edit,Glob,Grep,mcp__openhort__*
  --model claude-sonnet-4-6        # optional model override
  --resume <session_id>            # continue conversation
  --system-prompt "..."            # first message only
  --append-system-prompt "..."     # mobile: plain text, no markdown
  "user message"                   # the actual prompt
```

- `--bare` disables Keychain reads — auth strictly via `apiKeyHelper` in settings
- `--allowedTools` whitelists specific tools (default, NOT `--dangerously-skip-permissions`)
- `--resume` enables multi-turn conversations (session ID from previous response)

## MCP Bridge

The host runs an MCP SSE server that exposes all plugin tools to Claude inside the container:

```json
{
  "mcpServers": {
    "openhort": {
      "type": "sse",
      "url": "http://host.docker.internal:PORT/sse"
    }
  }
}
```

Tools are namespaced: `{plugin_id}__{tool_name}` (e.g., `screenshot_capture__screenshot`).

The bridge discovers all extensions with `mcp=true` in their manifest and exposes their tools. Claude calls them via MCP JSON-RPC through the SSE connection.

## Session Management

### Shared Sessions (Groups)

Users in a group with `session: shared` share one Claude conversation across connectors:

```yaml
groups:
  owner:
    session: shared

users:
  michael:
    groups: [owner]
    match:
      telegram: alice_dev
      wire: user@example.com
```

Michael on Telegram and Michael on Wire share the same Claude session — same conversation history, same `--resume` session ID.

### Isolated Sessions

Users in a group with `session: isolated` get separate sessions per connector/conversation.

### User Resolution

When a message arrives:

1. Look up user in `hort-config.yaml` by connector match (`telegram: alice_dev`)
2. Find their group(s)
3. Determine session policy (`shared` → session key by user name, `isolated` → by conversation ID)
4. Route to Claude with the resolved session key

## Error Handling

Internal errors NEVER leak to users:

```python
except Exception:
    logger.exception("Chat backend error")
    return "Something went wrong. Try again."
```

This applies to all paths: Telegram, Wire, MCP tools, callback buttons. Full details go to `logs/openhort.log` only.

## Plugin Structure

```
extensions/core/claude_code/
  __init__.py
  extension.json          # manifest: capabilities, features, MCP
  provider.py             # ClaudeCodePlugin (PluginBase + MCPMixin)
  auth.py                 # cross-platform credential extraction
  stream.py               # stream-json parser
  typewriter.py           # character-by-character output
  tests/
    test_auth.py           # 7 tests: keychain, env, fallback
    test_plugin.py         # 6 tests: lifecycle, MCP tools, envoy config
    test_stream.py         # 5 tests: text delta, thinking, malformed
    test_typewriter.py     # 5 tests: output, bounds, large blocks
```

23 unit tests total, all passing.
