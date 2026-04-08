# Hort-to-Hort (H2H) Protocol

The protocol for communication between horts — parent to child, neighbor to neighbor, and across arbitrary nesting depths. Transport-agnostic: works over stdio, HTTP/WebSocket, or Unix sockets.

## Core Principle

A hort is an isolation boundary. The H2H protocol is how isolated systems talk to each other **without breaking isolation**. It is NOT limited to MCP — MCP is one capability a hort can expose, but a hort can also expose process management, file operations, credential provisioning, and any other capability the parent is permitted to use.

```
┌─────────────────────────────────────────────────────────┐
│ H2H Protocol                                             │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │   MCP    │  │ Process  │  │  Files   │  ...           │
│  │  Tools   │  │  Mgmt    │  │  & Auth  │               │
│  └──────────┘  └──────────┘  └──────────┘               │
│                                                          │
│  Transport: stdio | HTTP/WS | Unix socket                │
└─────────────────────────────────────────────────────────┘
```

## Connection Direction

**Rule: Parents connect to children. Never the reverse.**

```mermaid
graph TD
    subgraph mac ["🏠 macOS (root hort)"]
        A["🤖 Agent"]
    end
    
    subgraph docker ["🏠 Docker Container"]
        CL["🤖 Claude Code"]
    end
    
    subgraph vm ["🏠 Linux VM"]
        subgraph nested ["🏠 VM Container"]
            APP["📦 App"]
        end
    end
    
    A -->|"H2H"| docker
    A -->|"H2H"| vm
    vm -->|"H2H"| nested
    
    docker -.->|"❌ FORBIDDEN"| mac
    nested -.->|"❌ FORBIDDEN"| vm
```

A child hort cannot initiate connections upward. This is the fundamental security boundary — a compromised container cannot reach the host.

### Exception: Neighbor Horts

Two horts at the same level can be configured as **neighbors**. Both may initiate a connection; first one wins, second is dropped:

```mermaid
graph LR
    subgraph h1 ["🏠 Hort A"]
        A1["🤖 Agent A"]
    end
    
    subgraph h2 ["🏠 Hort B"]
        A2["🤖 Agent B"]
    end
    
    A1 <-->|"H2H neighbor · first wins"| A2
```

```yaml
neighbors:
  - hort_a: { host: 10.0.1.10, port: 8940 }
    hort_b: { host: 10.0.1.20, port: 8940 }
    rules:
      allow_groups: [read, write]
      deny_groups: [destroy]
```

Neighbor connections share the same underlying VMs and resources. The `WireRuleset` on the neighbor wire controls what each side can access.

## Transport Layers

The H2H protocol is transport-agnostic. The same message format works over any transport:

| Transport | Use Case | Latency | Overhead |
|---|---|---|---|
| **stdio** | Local containers, subprocess | Lowest | Zero (pipes) |
| **Unix socket** | Local VMs, sibling containers | Very low | Minimal |
| **HTTP/WebSocket** | Remote horts, cloud VMs, P2P | Higher | TLS, framing |

### Transport Selection

```mermaid
flowchart TD
    START["Child hort type?"] --> LOCAL{"Local process<br/>or container?"}
    LOCAL -->|"Yes"| STDIO["stdio<br/>(pipes)"]
    LOCAL -->|"No"| NETWORK{"Same machine?"}
    NETWORK -->|"Yes"| UNIX["Unix socket<br/>(/tmp/hort-{id}.sock)"]
    NETWORK -->|"No"| HTTP["HTTP/WebSocket<br/>(TLS)"]
```

### stdio Transport

Parent spawns child process. Communication over stdin/stdout pipes:

```
Parent                          Child (PID 1 in container)
  │                                │
  │──── JSON request ──────────→  │
  │                                │  (process request)
  │  ←── JSON response ────────── │
  │                                │
  │──── JSON request ──────────→  │
  │  ←── JSON stream chunks ───── │
  │  ←── JSON stream end ──────── │
```

No `docker exec` needed. The child's PID 1 IS the H2H agent. No process listings, no env var leaks.

### HTTP/WebSocket Transport

For remote horts or when stdio isn't available:

```
Parent                          Child
  │                                │
  │── POST /h2h/request ────────→ │
  │  ←── 200 JSON response ────── │
  │                                │
  │── WS /h2h/stream ──────────→ │
  │  ←── WS text frames ───────── │
```

### Unix Socket Transport

For local VMs or sibling containers sharing a socket mount:

```
Parent                          Child
  │                                │
  │── connect(/tmp/hort.sock) ──→ │
  │── JSON request ──────────────→ │
  │  ←── JSON response ──────────  │
```

## Message Format

All transports use the same JSON message format. One message per line (JSONL):

### Request

```json
{
  "id": "r1",
  "type": "request",
  "channel": "mcp",
  "method": "tools/call",
  "params": {
    "name": "screenshot",
    "arguments": {"window_id": 42}
  }
}
```

### Response

```json
{
  "id": "r1",
  "type": "response",
  "status": "ok",
  "result": {"image": "base64..."}
}
```

### Error

```json
{
  "id": "r1",
  "type": "error",
  "code": "permission_denied",
  "message": "Tool 'screenshot' not allowed by wire rules"
}
```

### Channels

The `channel` field routes messages to the right handler:

| Channel | Purpose | Examples |
|---|---|---|
| `mcp` | MCP tool calls and responses | `tools/list`, `tools/call` |
| `process` | Process lifecycle management | `start`, `stop`, `status`, `exec` |
| `fs` | File operations | `read`, `write`, `mkdir` |
| `auth` | Credential provisioning | `set_credential`, `rotate` |
| `stream` | Binary data streams | JPEG frames, log output |
| `control` | Connection management | `ping`, `shutdown`, `capabilities` |

Each channel can be independently allowed or denied per client via the `WireRuleset`.

### Capability Negotiation

On connection, parent sends a `capabilities` request. Child responds with what it supports:

```json
{"id": "c1", "type": "request", "channel": "control", "method": "capabilities"}
```

```json
{
  "id": "c1",
  "type": "response",
  "status": "ok",
  "result": {
    "channels": ["mcp", "process", "fs", "auth", "control"],
    "mcp_tools": ["screenshot", "list_windows", "click", "type"],
    "version": "1.0"
  }
}
```

## Nesting & Tree Routing

Horts form a tree. Requests can traverse multiple levels:

```mermaid
graph TD
    subgraph mac ["🏠 macOS · root"]
        M["🤖 Agent"]
    end
    
    subgraph vm ["🏠 Linux VM"]
        V["🤖 Agent"]
        subgraph c1 ["🏠 Container A"]
            A["📦 App A"]
        end
        subgraph c2 ["🏠 Container B"]
            B["📦 App B"]
        end
    end
    
    M -->|"H2H (HTTP/WS)"| V
    V -->|"H2H (stdio)"| c1
    V -->|"H2H (stdio)"| c2
```

### Routing via Host Path

The 12-char host IDs compose the routing chain (see [Unified Access](../security/unified-access.md)):

```
Xk9mPq2sY4vN                → Linux VM (first hop)
Xk9mPq2sY4vNaB3cD7eF8gHi    → Container A inside VM (two hops)
```

Each hort routes to the next:

```mermaid
sequenceDiagram
    participant Mac as macOS (root)
    participant VM as Linux VM
    participant C as Container A
    
    Mac->>VM: H2H request (host_path: Xk9mPq2sY4vNaB3cD7eF8gHi)
    Note over VM: Split path: ["Xk9mPq2sY4vN", "aB3cD7eF8gHi"]<br/>First chunk = me, strip and forward
    VM->>C: H2H request (host_path: aB3cD7eF8gHi)
    C-->>VM: H2H response
    VM-->>Mac: H2H response
```

### Wire Rules at Each Hop

Each hop applies its own `WireRuleset`. The request must pass ALL hops:

```mermaid
flowchart LR
    REQ["MCP tools/call<br/>screenshot"] --> H1{"Mac → VM<br/>wire rules"}
    H1 -->|"ALLOW"| H2{"VM → Container<br/>wire rules"}
    H2 -->|"ALLOW"| EXEC["Execute tool"]
    H1 -->|"DENY"| BLOCKED["BLOCKED"]
    H2 -->|"DENY"| BLOCKED
    
    style BLOCKED fill:#f44336,color:#fff
    style EXEC fill:#4caf50,color:#fff
```

A parent cannot grant MORE permissions than it has. Each hop can only further restrict:

```yaml
# Mac → VM wire: allows read + write
hort/linux-vm:
  allow_groups: [read, write]

# VM → Container wire: allows only read (further restricts)
hort/container-a:
  allow_groups: [read]
  # write is denied even though the parent allows it
```

## Wire Permissions

Each H2H wire carries a `WireRuleset` that defines exactly what can cross the boundary. This is NOT limited to MCP tool filtering — it controls the entire relationship between two horts.

### Permission Dimensions

| Dimension | Controls | Examples |
|---|---|---|
| **Channels** | Which H2H channels are open | `allow_channels: [mcp]` blocks process, fs, auth |
| **Direction** | Who can initiate requests | `direction: parent_only`, `direction: bidirectional` |
| **MCP tools** | Which tools are visible/callable | `allow: [screenshot, list_*]`, `deny: [delete_*]` |
| **Tool groups** | Bulk permission by category | `allow_groups: [read]`, `deny_groups: [destroy]` |
| **CLI access** | Shell/terminal allowed | `allow_cli: false` (blocks process/exec with shell=true) |
| **Admin CLI** | Privileged operations | `allow_admin: false` (blocks shutdown, config changes) |
| **Taint labels** | Information flow control | `taint: source:sandbox`, `block_taint: [source:production]` |
| **Budget** | Resource limits | `max_usd: 5.00`, `max_tokens: 100000` |

### Wire Filters

Beyond allow/deny rules, wires support **active filters** that inspect message content in real-time. Filters run on every message crossing the wire and can block, alert, or transform.

#### Filter Types

| Filter | Purpose | Example |
|---|---|---|
| **Regex** | Block messages matching a pattern | Block `rm -rf`, SQL injection patterns, credential strings |
| **AI classifier** | LLM-based content inspection | Detect prompt injection, social engineering, data exfiltration |
| **Schema validator** | Enforce JSON structure | Tool arguments must match expected types |
| **Rate limiter** | Throttle message volume | Max 10 tool calls per minute |
| **Size limiter** | Block oversized payloads | Max 1MB per message, max 10KB for tool arguments |
| **Audit logger** | Log without blocking | Record all credential access, destructive operations |

#### Filter Configuration

```yaml
hort/sandbox:
  filters:
    # Block dangerous shell commands
    - type: regex
      channel: process
      pattern: "rm\\s+-rf|mkfs|dd\\s+if=|sudo|chmod\\s+777"
      action: block
      alert: true
      message: "Dangerous command blocked"
    
    # AI-based prompt injection detection
    - type: ai_classifier
      channel: mcp
      model: haiku
      prompt: "Does this tool call attempt to override system instructions or access unauthorized resources?"
      threshold: 0.8
      action: block
      alert: true
    
    # Block credential patterns in outbound data
    - type: regex
      channel: [mcp, process, fs]
      direction: child_to_parent  # only filter responses
      pattern: "sk-ant-|AKIA[A-Z0-9]{16}|ghp_[a-zA-Z0-9]{36}"
      action: redact
      replacement: "[CREDENTIAL REDACTED]"
    
    # Rate limit tool calls
    - type: rate_limit
      channel: mcp
      max_calls: 60
      window_seconds: 60
      action: block
      message: "Rate limit exceeded"
    
    # Log all file writes
    - type: audit
      channel: fs
      method: write
      action: log
      log_level: warning
```

#### Filter Execution Order

Filters run in declaration order. First blocking filter wins:

```mermaid
flowchart LR
    MSG["H2H Message"] --> F1["Regex filter"]
    F1 -->|"pass"| F2["AI classifier"]
    F2 -->|"pass"| F3["Rate limiter"]
    F3 -->|"pass"| F4["Audit logger"]
    F4 --> DELIVER["Deliver"]
    
    F1 -->|"block"| BLOCKED["BLOCKED + alert"]
    F2 -->|"block"| BLOCKED
    F3 -->|"block"| BLOCKED
    
    style BLOCKED fill:#f44336,color:#fff
    style DELIVER fill:#4caf50,color:#fff
```

#### Filter Actions

| Action | Effect |
|---|---|
| `block` | Message dropped. Error returned to sender. Optional alert to admin. |
| `alert` | Message delivered but admin notified (status bar, log, Telegram). |
| `redact` | Matching content replaced with placeholder. Message delivered. |
| `log` | Message delivered. Full content written to audit log. |
| `transform` | Message modified (e.g., sanitize HTML, strip metadata). Delivered. |

### Direction Control

Not all wires are request-response. The direction determines who can initiate:

```yaml
# Parent sends commands, child only responds
hort/sandbox:
  direction: parent_only
  allow_channels: [mcp, process, auth]

# Both can initiate (neighbor horts)
hort/office:
  direction: bidirectional
  allow_channels: [mcp]

# Child can push events (e.g. webhook notifications) but not request
hort/webhook-receiver:
  direction: child_push
  allow_channels: [mcp]
  allow: [on_webhook_received]  # child can only call this one tool on parent
```

```mermaid
graph LR
    subgraph parent_only ["direction: parent_only"]
        P1["🏠 Parent"] -->|"requests"| C1["🏠 Child"]
        C1 -->|"responses only"| P1
    end
```

```mermaid
graph LR
    subgraph bidirectional ["direction: bidirectional"]
        P2["🏠 Hort A"] <-->|"both can initiate"| C2["🏠 Hort B"]
    end
```

```mermaid
graph LR
    subgraph child_push ["direction: child_push"]
        P3["🏠 Parent"] -->|"requests"| C3["🏠 Child"]
        C3 -->|"responses + events"| P3
    end
```

### Full Permission Example

```yaml
# Sandbox for untrusted code execution
hort/sandbox:
  direction: parent_only
  allow_channels: [mcp, process, fs, auth]
  allow_groups: [read, write]
  deny_groups: [destroy, send]
  allow: [exec_command, read_file, write_file, list_files]
  deny: [delete_*, send_*, shutdown, reboot]
  allow_cli: true
  allow_admin: false
  taint: source:sandbox
  block_taint: [source:production, content:credentials]
  budget: { max_usd: 2.00 }

# Guest viewer — can only look, never act
hort/guest-view:
  direction: parent_only
  allow_channels: [mcp]
  allow_groups: [read]
  deny_groups: [write, send, destroy]
  allow_cli: false
  allow_admin: false

# Neighbor office machine — bidirectional but MCP-only
hort/office:
  direction: bidirectional
  allow_channels: [mcp]
  allow_groups: [read, write]
  deny_groups: [destroy]
  deny: [exec_command, send_email]
  allow_cli: false
  allow_admin: false

# Hosted app — can push webhook events, otherwise respond-only
hort/workflow-engine:
  direction: child_push
  allow_channels: [mcp]
  allow: [on_workflow_complete, on_error]  # child can push these events
  allow_groups: [read, write]             # parent can call these on child
  allow_cli: false
  allow_admin: false
```

### Per-Wire MCP Filtering

The same hort exposes different tool sets to different clients:

```mermaid
graph TD
    subgraph hort ["🏠 Hort with 10 MCP tools"]
        T1["screenshot"]
        T2["list_windows"]
        T3["click"]
        T4["type_text"]
        T5["read_file"]
        T6["write_file"]
        T7["delete_file"]
        T8["exec_command"]
        T9["send_email"]
        T10["get_status"]
    end
    
    subgraph owner ["👤 Owner"]
        O["Sees all 10 tools<br/>+ CLI + admin"]
    end
    
    subgraph guest ["👤 Guest"]
        G["Sees: screenshot,<br/>list_windows, get_status<br/>No CLI, no admin"]
    end
    
    subgraph sandbox ["🏠 Sandbox"]
        S["Sees: read_file,<br/>exec_command<br/>CLI yes, admin no"]
    end
    
    hort -->|"allow: * · allow_cli · allow_admin"| owner
    hort -->|"allow_groups: [read] · no CLI"| guest
    hort -->|"allow: [read_file, exec_command]<br/>allow_cli · deny: [delete_*]"| sandbox
```

### Channel + Direction + Tools = Complete Control

The three dimensions compose:

```mermaid
flowchart TD
    REQ["Incoming H2H message"] --> D{"Direction<br/>allowed?"}
    D -->|"No (child→parent<br/>on parent_only wire)"| DROP["DROP + LOG"]
    D -->|"Yes"| CH{"Channel<br/>allowed?"}
    CH -->|"No (fs on mcp-only wire)"| DROP
    CH -->|"Yes"| TOOL{"Tool/method<br/>allowed?"}
    TOOL -->|"No (delete_file on<br/>read-only wire)"| DROP
    TOOL -->|"Yes"| CLI{"CLI access<br/>required?"}
    CLI -->|"shell=true but<br/>allow_cli=false"| DROP
    CLI -->|"OK"| ADMIN{"Admin op?"}
    ADMIN -->|"shutdown but<br/>allow_admin=false"| DROP
    ADMIN -->|"OK"| TAINT{"Taint<br/>allowed?"}
    TAINT -->|"source:production on<br/>sandbox wire"| DROP
    TAINT -->|"OK"| EXEC["EXECUTE"]
    
    style DROP fill:#f44336,color:#fff
    style EXEC fill:#4caf50,color:#fff
```

## Security Model

### Isolation Guarantee

A child hort CANNOT:

- Initiate connections to its parent
- Access the parent's filesystem
- Read the parent's environment variables
- Discover sibling horts
- Escalate from a VM to the host
- Execute commands on the parent

A child hort CAN ONLY:

- Respond to requests from its parent
- Use capabilities negotiated at connection time
- Access resources explicitly granted via the wire ruleset

### Credential Flow

Credentials flow **downward only**, via the `auth` channel:

```mermaid
sequenceDiagram
    participant Mac as macOS (parent)
    participant Container as Container (child)
    
    Mac->>Container: auth/set_credential<br/>{name: "api_key", value: "sk-..."}
    Note over Container: Stores in memory only.<br/>Never persisted to disk.
    Container-->>Mac: ok
    
    Mac->>Container: process/start<br/>{cmd: "claude", args: ["-p", "hello"]}
    Note over Container: Process receives credential<br/>via in-memory injection.<br/>Not in env, not in /proc.
    Container-->>Mac: {pid: 42, status: "running"}
```

### No Upward Escalation

Even if a process inside a container is compromised:

```mermaid
graph TD
    subgraph mac ["🏠 macOS"]
        AGENT["🤖 Host Agent"]
        H2H["H2H Listener"]
    end
    
    subgraph container ["🏠 Container (compromised)"]
        EVIL["💀 Malicious Process"]
        STDIO["stdin/stdout<br/>(H2H protocol only)"]
    end
    
    H2H -->|"requests"| STDIO
    STDIO -->|"responses only"| H2H
    
    EVIL -->|"❌ No network to host"| mac
    EVIL -->|"❌ No mount to host FS"| mac
    EVIL -->|"❌ No docker socket"| mac
    EVIL -->|"❌ Can only write to stdout<br/>(parent validates all messages)"| STDIO
```

The parent validates every message from the child. Invalid channels, unauthorized methods, or malformed messages are dropped and logged.

## Constellation Examples

### Example 1: Development Machine

```mermaid
graph TD
    subgraph mac ["🏠 macOS · Xk9mPq2sY4vN"]
        AGENT["🤖 Claude Code"]
        TG["📦 Telegram"]
        LENS["📦 LlmingLens"]
        WIRE["📦 LlmingWire"]
    end
    
    subgraph sandbox ["🏠 Sandbox · aB3cD7eF8gHi<br/>stdio transport"]
        CLAUDE["🤖 Claude (sandboxed)"]
        TOOLS["📦 MCP Tools (proxied)"]
    end
    
    subgraph hosted ["🏠 Hosted App · jK5lM6nO9pQr<br/>HTTP transport"]
        WF["📦 Workflow Engine"]
    end
    
    AGENT --> TG
    AGENT --> LENS
    AGENT --> WIRE
    AGENT -->|"H2H · allow: [mcp, process]<br/>deny: [fs, auth]"| sandbox
    AGENT -->|"H2H · allow: [mcp]"| hosted
```

### Example 2: Remote VM with Nested Containers

```mermaid
graph TD
    subgraph mac ["🏠 macOS · Xk9mPq2sY4vN"]
        M["🤖 Agent"]
    end
    
    subgraph azure ["🏠 Azure VM · aB3cD7eF8gHi<br/>HTTP/WS transport"]
        VA["🤖 VM Agent"]
        
        subgraph dev ["🏠 Dev Container · jK5lM6nO9pQr<br/>stdio transport"]
            CODE["📦 Code Server"]
            SHELL["📦 Shell"]
        end
        
        subgraph prod ["🏠 Prod Container · mN7oP8qR1sT2<br/>stdio transport"]
            APP["📦 Production App"]
        end
    end
    
    M -->|"H2H · allow: [mcp, process, fs]"| VA
    VA -->|"H2H · allow: [mcp, process, fs]"| dev
    VA -->|"H2H · allow: [mcp] · deny: [process, fs]"| prod
```

Full host paths:

- Dev container: `Xk9mPq2sY4vNaB3cD7eF8gHijK5lM6nO9pQr` (36 chars = 3 hops)
- Prod container: `Xk9mPq2sY4vNaB3cD7eF8gHimN7oP8qR1sT2` (36 chars = 3 hops)

### Example 3: Neighbor Horts (Home + Office)

```mermaid
graph LR
    subgraph home ["🏠 Home Mac · Xk9mPq2sY4vN"]
        H["🤖 Agent"]
        HFS["📦 Home Files"]
    end
    
    subgraph office ["🏠 Office Mac · aB3cD7eF8gHi"]
        O["🤖 Agent"]
        OFS["📦 Office Files"]
        SAP["📦 SAP"]
    end
    
    H <-->|"H2H neighbor · WireGuard<br/>allow: [mcp] · deny: [process, fs]"| O
```

Both can initiate. First connection wins. Neither can exec processes on the other — only MCP tool calls cross the wire.

### Example 4: Shared Access (Guest)

```mermaid
graph TD
    subgraph owner ["🏠 Owner's Mac · Xk9mPq2sY4vN"]
        OA["🤖 Owner Agent"]
        
        subgraph shared ["🏠 Shared VM · aB3cD7eF8gHi"]
            SA["🤖 Shared Agent"]
            CODE["📦 Code Server"]
            TERM["📦 Terminal"]
        end
    end
    
    subgraph guest ["👤 Guest (Sarah)"]
        GB["🌐 Browser"]
    end
    
    OA -->|"H2H · full access"| shared
    GB -->|"H2H · allow: [mcp]<br/>deny: [process, fs, auth]"| shared
```

The guest connects to the shared VM directly (via proxy or P2P). Wire rules on the guest connection restrict to MCP-only — no process management, no filesystem, no credential access.

### Example 5: Multi-Tier with Mixed Transports

```mermaid
graph TD
    subgraph mac ["🏠 macOS (root)"]
        M["🤖 Agent"]
    end
    
    subgraph vm ["🏠 Linux VM<br/>Unix socket transport"]
        V["🤖 VM Agent"]
        
        subgraph c_claude ["🏠 Claude Sandbox<br/>stdio transport"]
            CL["🤖 Claude"]
        end
        
        subgraph c_app ["🏠 App Container<br/>stdio transport"]
            APP["📦 Web App"]
        end
    end
    
    subgraph remote ["🏠 Cloud Worker<br/>HTTP/WS transport"]
        R["🤖 Remote Agent"]
        
        subgraph rc ["🏠 Remote Container<br/>stdio transport"]
            RC["📦 Compute"]
        end
    end
    
    M -->|"Unix socket"| V
    V -->|"stdio"| c_claude
    V -->|"stdio"| c_app
    M -->|"HTTP/WS (TLS)"| R
    R -->|"stdio"| rc
```

Four different transports in one tree:

- Mac → VM: Unix socket (same machine, fast)
- VM → Containers: stdio (local processes)
- Mac → Cloud: HTTP/WS with TLS (remote)
- Cloud → Container: stdio (local to cloud VM)

## Container Agent Implementation

Instead of `docker exec` (current), each container runs a **H2H agent** as PID 1:

```dockerfile
ENTRYPOINT ["hort-agent"]
```

The agent:

1. Reads JSONL from stdin (or listens on socket/HTTP)
2. Routes by `channel` to internal handlers
3. Validates permissions against the wire ruleset received at startup
4. Responds via stdout (or socket/HTTP)
5. Never initiates outbound connections

### Migration Path

| Current (docker exec) | H2H Agent |
|---|---|
| `docker exec -e KEY=val cmd` | `auth/set_credential` + `process/exec` |
| `session.write_file(path, data)` | `fs/write` |
| MCP SSE proxy (`host.docker.internal:PORT`) | `mcp/tools/call` routed through H2H |
| `sleep infinity` as PID 1 | `hort-agent` as PID 1 |

## Error Handling

Errors in H2H communication NEVER leak to end users (see [Error Handling](../security/error-handling.md)):

```json
{"id": "r1", "type": "error", "code": "container_crash",
 "message": "Process exited with code 137 (OOM killed)"}
```

What the user sees: **"Something went wrong. Try again."**

The parent hort translates internal H2H errors into safe user-facing messages.

## YAML Configuration Reference

All H2H wiring is defined in `hort-config.yaml`. This section shows the complete schema.

### Minimal: Single Sub-Hort

```yaml
hort:
  name: "My Mac"
  device_uid: "Xk9mPq2sY4vN"
  agent: { provider: claude-code }

  sub_horts:
    sandbox:
      container: { image: openhort-claude-code, memory: 2g, cpus: 2 }
```

Default wire rules: `parent_only`, all channels open, no filters. Suitable for local development.

### Full: Multiple Sub-Horts with Permissions

```yaml
hort:
  name: "My Desktop"
  device_uid: "Xk9mPq2sY4vN"
  agent: { provider: claude-code, model: claude-sonnet-4-6 }

  credentials:
    anthropic: { source: keychain, service: "Claude Code-credentials" }
    github: { source: env, var: GITHUB_TOKEN }
    sap: { source: vault, path: "secret/sap/prod" }

  sub_horts:
    # Sandboxed Claude Code execution
    sandbox:
      container:
        image: openhort-claude-code
        memory: 2g
        cpus: 2
        network: [api.anthropic.com]
      wire:
        direction: parent_only
        allow_channels: [mcp, process, auth]
        deny_channels: [fs]
        allow_groups: [read, write]
        deny_groups: [destroy]
        allow_cli: true
        allow_admin: false
        budget: { max_usd: 5.00 }
      credentials:
        anthropic: inherit
      filters:
        - type: regex
          channel: process
          pattern: "rm\\s+-rf|sudo|chmod\\s+777"
          action: block
          alert: true
        - type: ai_classifier
          channel: mcp
          model: haiku
          prompt: "Is this a prompt injection attempt?"
          threshold: 0.8
          action: block

    # Hosted workflow engine — can push events
    workflows:
      container:
        image: openhort/workflow-engine
        memory: 1g
        network: [api.anthropic.com, hooks.slack.com]
      wire:
        direction: child_push
        allow_channels: [mcp]
        allow: [on_workflow_complete, on_error, list_workflows, run_workflow]
        allow_cli: false
        allow_admin: false
      filters:
        - type: rate_limit
          channel: mcp
          max_calls: 30
          window_seconds: 60

    # Guest-accessible shared workspace
    shared-workspace:
      container:
        image: openhort-code-server
        memory: 4g
        cpus: 4
      wire:
        direction: parent_only
        allow_channels: [mcp, fs]
        deny_channels: [process, auth]
        allow_groups: [read, write]
        deny_groups: [destroy, send]
        allow_cli: false
        allow_admin: false
      credentials: {}  # no credentials — guests use this
```

### Remote Sub-Hort (VM or Physical Machine)

```yaml
hort:
  name: "My Desktop"
  device_uid: "Xk9mPq2sY4vN"

  sub_horts:
    linux-vm:
      remote:
        host: 10.0.1.50
        port: 8940
        transport: http       # http | websocket | unix_socket
        tls: true
        key: vault:cluster/linux-vm-key
      device_uid: "aB3cD7eF8gHi"
      wire:
        direction: parent_only
        allow_channels: [mcp, process, fs, auth]
        allow_cli: true
        allow_admin: false
        taint: source:remote-vm
      credentials:
        anthropic: inherit
        github: inherit
```

### Neighbor Horts

```yaml
hort:
  name: "Home Mac"
  device_uid: "Xk9mPq2sY4vN"

  neighbors:
    office:
      remote:
        host: office.vpn.local
        port: 8940
        transport: websocket
        tls: true
        key: vault:cluster/office-key
      device_uid: "aB3cD7eF8gHi"
      wire:
        direction: bidirectional
        allow_channels: [mcp]
        deny_channels: [process, fs, auth]
        allow_groups: [read, write]
        deny_groups: [destroy]
        allow_cli: false
        allow_admin: false
      filters:
        - type: regex
          direction: both
          pattern: "sk-ant-|password|secret"
          action: redact
          replacement: "[REDACTED]"
```

### Nested: VM with Containers Inside

```yaml
hort:
  name: "My Desktop"
  device_uid: "Xk9mPq2sY4vN"

  sub_horts:
    azure-vm:
      remote:
        host: worker.eastus.azure.com
        port: 8940
        transport: websocket
        tls: true
      device_uid: "aB3cD7eF8gHi"
      wire:
        direction: parent_only
        allow_channels: [mcp, process, fs, auth]

      # The VM itself has sub-horts (containers)
      sub_horts:
        dev-container:
          container: { image: openhort-dev, memory: 4g }
          device_uid: "jK5lM6nO9pQr"
          wire:
            direction: parent_only
            allow_channels: [mcp, process, fs]
            allow_cli: true

        prod-container:
          container: { image: openhort-prod, memory: 2g }
          device_uid: "mN7oP8qR1sT2"
          wire:
            direction: parent_only
            allow_channels: [mcp]
            deny_channels: [process, fs, auth]
            allow_cli: false
            allow_admin: false
```

Host paths resolve automatically:

- `Xk9mPq2sY4vN` → root (macOS)
- `Xk9mPq2sY4vNaB3cD7eF8gHi` → Azure VM
- `Xk9mPq2sY4vNaB3cD7eF8gHijK5lM6nO9pQr` → dev container inside VM
- `Xk9mPq2sY4vNaB3cD7eF8gHimN7oP8qR1sT2` → prod container inside VM

### Complete Wire Schema

```yaml
wire:
  # Direction control
  direction: parent_only | bidirectional | child_push

  # Channel permissions
  allow_channels: [mcp, process, fs, auth, stream, control]
  deny_channels: []

  # MCP tool permissions
  allow: [tool_glob_pattern, ...]          # e.g. [read_*, list_*, screenshot]
  deny: [tool_glob_pattern, ...]           # e.g. [delete_*, send_*]
  allow_groups: [read, write, send, destroy]
  deny_groups: [destroy]

  # CLI and admin access
  allow_cli: true | false                  # shell/terminal execution
  allow_admin: true | false                # shutdown, config changes, user management

  # Information flow control
  taint: source:sandbox                    # label applied to all data crossing this wire
  block_taint: [source:production]         # data with these labels cannot cross

  # Resource limits
  budget:
    max_usd: 5.00                          # max API spend
    max_tokens: 100000                     # max token usage
    max_calls: 1000                        # max total tool calls

  # Metadata
  name: "sandbox wire"
  color: "#3b82f6"

# Filters (ordered, first blocking filter wins)
filters:
  - type: regex | ai_classifier | schema | rate_limit | size_limit | audit
    channel: mcp | process | fs | [mcp, process]    # which channels to filter
    direction: both | parent_to_child | child_to_parent
    pattern: "..."                         # for regex
    model: haiku                           # for ai_classifier
    prompt: "..."                          # for ai_classifier
    threshold: 0.8                         # for ai_classifier
    max_calls: 60                          # for rate_limit
    window_seconds: 60                     # for rate_limit
    max_bytes: 1048576                     # for size_limit
    action: block | alert | redact | log | transform
    alert: true | false                    # notify admin
    message: "Human-readable reason"
    replacement: "[REDACTED]"              # for redact action

# Credential inheritance
credentials:
  credential_name: inherit                 # receives from parent
  # Unlisted credentials are NOT available to this hort
```

## Related

- [Credential Provisioning](../security/credential-provisioning.md) — how credentials flow from OS stores to containers, cross-platform support
- [Unified Access](../security/unified-access.md) — host IDs, pairing, routing
- [Wiring Model](../security/wiring-model.md) — the four wiring forms and WireRuleset
- [Error Handling](../security/error-handling.md) — no internal errors to users
