# MCP Servers

Dynamic MCP (Model Context Protocol) server assignment for Claude chat
sessions. MCPs can run on the host, inside a container, or as remote
HTTP services — with per-server tool filtering.

## Overview

```mermaid
flowchart TD
    CLI["CLI: --mcp / --mcp-config"]
    CLI --> Parse["Parse config"]
    Parse --> Resolve{"Resolve routing"}
    Resolve -->|"direct"| Direct["Direct stdio\n(no proxy)"]
    Resolve -->|"proxied"| Proxy["SSE Proxy\non host"]
    Direct --> Config["Write MCP config JSON"]
    Proxy --> Config
    Config --> Claude["claude -p --mcp-config ...\n--disallowedTools ..."]
```

An MCP server can be **stdio** (a local command) or **HTTP** (a remote
URL). Both types work in local mode and container mode. Tool filtering
applies to both.

## Transport Types

### Stdio MCP

A process on the local machine. Claude starts it, communicates via
stdin/stdout using Content-Length framed JSON-RPC.

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/tmp"]
    }
  }
}
```

### HTTP MCP

An already-running server reachable via URL. Claude connects using the
MCP SSE transport (Server-Sent Events + POST).

```json
{
  "mcpServers": {
    "database": {
      "url": "http://localhost:3000/sse"
    }
  }
}
```

## Routing Decision

Every MCP server is classified as **direct** (Claude talks to it
directly) or **proxied** (goes through an SSE proxy on the host).

```mermaid
flowchart TD
    S["MCP Server"] --> Q1{"Container mode +\nscope outside/auto?"}
    Q1 -->|Yes| P["Proxied\n(SSE bridge on host)"]
    Q1 -->|No| Q2{"Has allow-list\ntool filter?"}
    Q2 -->|Yes| P
    Q2 -->|No| D["Direct\n(stdio or URL passthrough)"]

    P --> PF["Filtering in proxy:\ntools/list interception\ntools/call blocking"]
    D --> Q3{"Has deny-list\ntool filter?"}
    Q3 -->|Yes| DF["--disallowedTools\nflag on Claude CLI"]
    Q3 -->|No| NF["No filtering"]
```

!!! info "Why allow-lists always need a proxy"
    An allow-list means "only these tools exist." This requires
    intercepting the `tools/list` response from the MCP and removing
    unlisted tools before Claude sees them. The proxy sits between
    Claude and the MCP to do this.

    A deny-list means "all tools except these." Claude CLI natively
    supports `--disallowedTools`, so no proxy is needed — the flag
    handles it directly.

## Architecture

### Local Mode (no container)

```mermaid
flowchart LR
    subgraph Host ["Host Machine"]
        subgraph Direct ["Direct MCPs"]
            MCP_A["MCP A\n(stdio)"]
            MCP_B["MCP B\n(HTTP)"]
        end

        subgraph Filtered ["Filtered MCPs (via proxy)"]
            MCP_C["MCP C\n(stdio)"] <-->|stdio| Proxy["SSE Proxy\n:PORT"]
        end

        Claude["claude -p\n--mcp-config config.json\n--disallowedTools ..."]
        Claude <-->|stdio| MCP_A
        Claude <-->|HTTP| MCP_B
        Claude <-->|SSE| Proxy
    end
```

In local mode, most MCPs connect directly. A proxy is only started
when an MCP has an allow-list tool filter (needs `tools/list`
interception).

### Container Mode

```mermaid
flowchart TB
    subgraph Host ["Host Machine"]
        MCP_Out["MCP Server\n(outside, stdio)"]
        MCP_Http["MCP Server\n(outside, HTTP)"]
        MCP_Out <-->|stdio| Proxy["SSE Proxy\n:PORT + filtering"]

        subgraph Container ["Docker: claude-chat-sandbox"]
            Claude["claude -p --bare\n--mcp-config config.json\n--disallowedTools ..."]
            MCP_In["MCP Server\n(inside, stdio)"]
            Claude <-->|stdio| MCP_In
        end

        Claude <-->|"SSE via\nhost.docker.internal"| Proxy
        Claude <-->|"HTTP via\nhost.docker.internal\nor direct URL"| MCP_Http
    end
```

In container mode, MCPs with `scope: outside` or `scope: auto` run
on the host. Stdio MCPs go through the SSE proxy so Claude inside
the container can reach them. HTTP MCPs are accessible if the URL
is reachable from the container.

MCPs with `scope: inside` run directly inside the container (the
command must be available in the Docker image).

## SSE Proxy

The proxy bridges a stdio MCP process to the MCP SSE transport
protocol. It also applies tool filtering at the protocol level.

```mermaid
sequenceDiagram
    participant C as Claude (client)
    participant P as SSE Proxy
    participant M as MCP Server (stdio)

    C->>P: GET /sse
    P-->>C: event: endpoint<br/>data: /message?sessionId=abc

    C->>P: POST /message (initialize)
    P->>M: stdin: initialize
    M->>P: stdout: capabilities
    P-->>C: event: message (capabilities)

    C->>P: POST /message (tools/list)
    P->>M: stdin: tools/list
    M->>P: stdout: [read, write, delete]
    Note over P: Apply filter:<br/>allow=[read] → remove write, delete
    P-->>C: event: message ([read])

    C->>P: POST /message (tools/call: delete)
    Note over P: Filter check: delete blocked
    P-->>C: event: message (error: not allowed)

    C->>P: POST /message (tools/call: read)
    P->>M: stdin: tools/call read
    M->>P: stdout: result
    P-->>C: event: message (result)
```

### Proxy lifecycle

The `ProxyManager` runs all proxies in a background asyncio event
loop on a daemon thread. Proxies start before the first chat turn
and stop when the session ends.

```mermaid
stateDiagram-v2
    [*] --> Created: ProxyManager()
    Created --> Running: start(servers)
    Running --> Running: proxies serve requests
    Running --> Stopped: stop()
    Stopped --> [*]

    state Running {
        [*] --> EventLoop: background thread
        EventLoop --> ProxyA: McpSseProxy
        EventLoop --> ProxyB: McpSseProxy
    }
```

## Tool Filtering

Control which tools from an MCP server are visible to Claude.

### Allow list

Only the listed tools exist. All others are hidden.

```json
{
  "toolFilter": {
    "allow": ["read_file", "list_directory"]
  }
}
```

- `tools/list` response is intercepted — unlisted tools removed
- `tools/call` for unlisted tools returns JSON-RPC error
- Always routed through the proxy (needs response interception)

### Deny list

All tools are available except the listed ones.

```json
{
  "toolFilter": {
    "deny": ["delete_file", "write_file"]
  }
}
```

- Direct MCPs: handled via `--disallowedTools` CLI flag
- Proxied MCPs: handled at proxy level (same interception as allow)
- `tools/call` for denied tools returns JSON-RPC error

### Combined

Both can be used together. Allow is applied first, then deny.

```json
{
  "toolFilter": {
    "allow": ["read_file", "write_file", "list_dir"],
    "deny": ["write_file"]
  }
}
```

Result: only `read_file` and `list_dir` are available.

## Configuration

### CLI flags

```bash
# Inline MCP (stdio, no filtering)
--mcp "name=command arg1 arg2"

# Config file (full control)
--mcp-config path/to/mcps.json

# Both can be combined — inline MCPs merge into the config
--mcp-config mcps.json --mcp "extra=some-command"
```

### Config file format

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/tmp"],
      "env": {"HOME": "/tmp"},
      "scope": "outside",
      "toolFilter": {
        "allow": ["read_file", "list_directory"]
      }
    },
    "database": {
      "url": "http://localhost:5432/mcp",
      "scope": "outside",
      "toolFilter": {
        "deny": ["drop_table", "truncate"]
      }
    },
    "linter": {
      "command": "python",
      "args": ["-m", "mcp_linter"],
      "scope": "inside"
    }
  }
}
```

### Field reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | string | — | Executable for stdio MCPs |
| `args` | list | `[]` | Arguments for the command |
| `env` | object | `{}` | Extra environment variables |
| `url` | string | — | URL for HTTP/SSE MCPs (mutually exclusive with `command`) |
| `scope` | string | `auto` | `inside`, `outside`, or `auto` |
| `toolFilter` | object | — | Tool allow/deny filter |
| `toolFilter.allow` | list | — | Whitelist: only these tools are visible |
| `toolFilter.deny` | list | — | Blacklist: these tools are hidden |

### Scope behavior

| Scope | Local mode | Container mode |
|-------|-----------|---------------|
| `auto` | Direct (or proxy if allow-filter) | Proxied on host |
| `inside` | Direct | Runs inside container |
| `outside` | Direct (or proxy if allow-filter) | Proxied on host |

!!! warning "Inside scope + allow filter"
    Inside-container MCPs cannot have allow-list filters because
    there is no proxy to intercept `tools/list` inside the container.
    Use `scope: outside` instead, or switch to a deny-list filter
    (handled natively by `--disallowedTools`).

## Examples

### Read-only filesystem access

Give Claude file reading but block writes and deletes:

=== "Inline"

    ```bash
    poetry run python -m hort.extensions.claude_chat \
      --mcp "fs=npx -y @anthropic/mcp-filesystem /home/user/project" \
      --mcp-config <(echo '{"mcpServers":{"fs":{"command":"npx","args":["-y","@anthropic/mcp-filesystem","/home/user/project"],"toolFilter":{"deny":["write_file","create_directory","move_file"]}}}}')
    ```

=== "Config file"

    ```json
    {
      "mcpServers": {
        "fs": {
          "command": "npx",
          "args": ["-y", "@anthropic/mcp-filesystem", "/home/user/project"],
          "toolFilter": {
            "deny": ["write_file", "create_directory", "move_file"]
          }
        }
      }
    }
    ```

### Sandboxed container with host database

Claude runs in a container but queries a database on the host:

```json
{
  "mcpServers": {
    "db": {
      "url": "http://localhost:5432/mcp",
      "scope": "outside",
      "toolFilter": {
        "allow": ["query_table", "list_tables"],
        "deny": ["drop_table"]
      }
    }
  }
}
```

```bash
poetry run python -m hort.extensions.claude_chat \
  --container --memory 1g --cpus 2 \
  --mcp-config db-config.json
```

### Multiple MCPs with mixed scopes

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-github"],
      "env": {"GITHUB_TOKEN": "ghp_..."},
      "scope": "outside",
      "toolFilter": {
        "deny": ["delete_repository", "delete_branch"]
      }
    },
    "linter": {
      "command": "python",
      "args": ["-m", "pylint_mcp"],
      "scope": "inside"
    },
    "docs": {
      "url": "http://docs-service.internal:8080/mcp",
      "scope": "outside"
    }
  }
}
```

## Implementation Details

### Module structure

```
hort/sandbox/
  mcp.py           — config models, parsing, scope resolution, filtering
  mcp_proxy.py     — McpSseProxy (stdio↔SSE bridge), ProxyManager

hort/extensions/claude_chat/
  chat.py          — integrates MCP setup into the chat loop
```

### Data flow (full)

```mermaid
flowchart TD
    A["CLI args:\n--mcp, --mcp-config"] --> B["Parse into\nMcpConfig"]
    B --> C["resolve_servers()"]
    C --> D["direct_servers"]
    C --> E["proxied_servers"]
    E --> F["ProxyManager.start()"]
    F --> G["McpSseProxy per server\n(background event loop)"]
    G --> H["proxy_urls\n{name: http://...}"]
    D --> I["build_claude_mcp_json()"]
    H --> I
    I --> J["Write config file"]
    D --> K["compute_disallowed_tools()"]
    J --> L["--mcp-config path"]
    K --> M["--disallowedTools list"]
    L --> N["claude -p ... user_input"]
    M --> N
```

### Config generation

The system produces two inputs for each `claude -p` invocation:

1. **`--mcp-config`** — JSON file with `mcpServers` entries:
    - Direct stdio MCPs: `{"command": ..., "args": ...}`
    - Proxied MCPs: `{"url": "http://..."}`

2. **`--disallowedTools`** — comma-separated list of
   `mcp__<server>__<tool>` patterns for deny-list filtering on
   direct MCPs.

### Container networking

Docker containers reach the host via `host.docker.internal`. The
container is created with `--add-host=host.docker.internal:host-gateway`
for portability across macOS and Linux Docker.

The SSE proxy's endpoint URL is constructed from the HTTP `Host`
header of the incoming connection. This means the endpoint URL
automatically matches however the client connected — whether via
`localhost` (local mode) or `host.docker.internal` (container mode).

### Test coverage

| Test file | Tests | Covers |
|-----------|-------|--------|
| `test_mcp.py` | 21 | Config parsing, inline MCP specs, scope resolution, JSON generation, allow/deny filtering |
| `test_mcp_proxy.py` | 11 | Proxy lifecycle, SSE protocol, message roundtrip, tool list filtering, tool call blocking, ProxyManager |
| `test_extension_mcp.py` | 23 | MCP bridge routing, tool namespacing, LlmingLens tools (filters, grid, screenshot) |
| `test_chat_backend.py` | 9 | Chat session lifecycle, result parsing, tool tracking, security guard |

Proxy tests use a real mock MCP subprocess (Python script speaking
the stdio protocol) for full end-to-end verification.

## In-Process MCP Bridge

The MCP bridge (`hort/mcp/`) aggregates tools from all `MCPMixin`
extensions and serves them as a single MCP server. Unlike the SSE
proxy (which wraps external stdio MCP subprocesses), the bridge runs
tools **in-process** — the extension code executes directly.

### Architecture

```
Extension (MCPMixin)          MCP Bridge              Claude Code
┌──────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ llming-lens      │    │                  │    │                 │
│  - list_windows  │───▶│  MCPBridge       │◀──▶│  claude -p      │
│  - screenshot    │    │  (JSON-RPC)      │    │  --mcp-config   │
│  - click         │    │                  │    │                 │
├──────────────────┤    │  Namespacing:    │    │  Connects via   │
│ system-monitor   │    │  {pid}__{tool}   │    │  SSE or stdio   │
│  - get_metrics   │───▶│                  │    │                 │
├──────────────────┤    │  Transports:     │    └─────────────────┘
│ disk-usage       │    │  - stdio (local) │
│  - get_disk      │───▶│  - SSE (container│
└──────────────────┘    └──────────────────┘
```

### Tool namespacing

Tools are namespaced as `{plugin_id}__{tool_name}` to avoid
collisions. For example, `llming-lens__screenshot` and
`system-monitor__get_system_metrics`.

### Running standalone

```bash
# Stdio mode (for local Claude Code)
python -m hort.mcp.server

# SSE mode (for containerized Claude Code or chat backend)
python -m hort.mcp.server --sse --port 9100

# With app filter for screen tools
python -m hort.mcp.server --app-filter "Chrome*,iTerm*"
```

### Key files

| File | Purpose |
|------|---------|
| `hort/mcp/bridge.py` | `MCPBridge` (JSON-RPC router), `MCPSseServer` (SSE transport), `run_stdio` |
| `hort/mcp/server.py` | Extension discovery, standalone launcher (`python -m hort.mcp`) |
| `hort/ext/mcp.py` | `MCPMixin`, `MCPToolDef`, `MCPToolResult` — the plugin interface |

## Chat Backend

The chat backend (`hort/ext/chat_backend.py`) is a connector-agnostic
layer that routes non-command messages from any connector (Telegram,
WhatsApp, Teams, web chat) to a chat provider (currently Claude Code).

### Flow

```
Telegram message "What's on my screen?"
  → TelegramConnector._handle() detects non-command
  → ChatBackendManager.get_session(user_id)
  → ChatSession.send(message)
  → claude -p --mcp-config bridge.json --resume SESSION_ID "message"
  → Claude uses openhort MCP tools (screenshot, list_windows, ...)
  → Response text returned
  → ConnectorResponse.simple(text) → Telegram
```

### Components

- **`ChatBackendManager`** — starts the MCP bridge subprocess,
  manages per-user sessions. Any connector creates one instance.
- **`ChatSession`** — wraps Claude Code CLI with `--resume` for
  conversation continuity. Parses `stream-json` output. Emits
  `ChatProgressEvent` for tool use and thinking status.
- **`MCPBridgeProcess`** — starts `python -m hort.mcp.server --sse`
  as a subprocess, auto-assigns port, writes MCP config JSON.
- **`ChatProgressEvent`** — typed progress events (`tool_start`,
  `thinking`, `typing`) that connectors render as they see fit.
  Telegram shows periodic "Working..." messages. A web chat could
  show individual tool names in a spinner.

### System prompt from SOUL.md

The system prompt is built dynamically from extension `SOUL.md` files
(see `docs/manual/develop/plugins.md`, section "SOUL.md — Agent Instructions").
Each extension's SOUL.md chapters are injected into the prompt.
Feature-gated chapters are included only when the feature is enabled.

The `system_prompt` in config is prepended as a base before any
SOUL.md content. If no SOUL.md files exist, a built-in default
prompt is used.

### Configuration

In `hort-config.yaml` under the connector's key:

```yaml
telegram-connector:
  allowed_users: [username]    # REQUIRED — chat refuses to start without it
  chat:
    enabled: true
    system_prompt: "Optional base prompt prepended before SOUL.md content"
    model: sonnet              # Claude model
    progress_interval: 8.0     # seconds between "Working..." updates
```

### Safety

- Chat backend **requires `allowed_users`** — it will not activate
  without an explicit user list. This is enforced in code.
- User activity detection: input tools (click, type, press_key)
  check for recent mouse/keyboard input and refuse to act if the
  user is actively interacting.
- Response sanitization: base64 data is stripped from responses,
  and text is capped at 8000 chars before sending to connectors.
- Asyncio subprocess buffer: set to 10 MB (`limit=10*1024*1024`)
  because Claude's `result` JSON lines can exceed the default 64 KB
  when MCP tools return screenshots. See
  Memory Safety (`docs/manual/develop/memory-safety.md`) rule 7.
