# Architecture

Technical internals for contributors and developers.

## Module Structure

```
hort/sandbox/                      ← CORE (covered by main test suite)
  __init__.py          — public API (Session, SessionConfig, SessionManager)
  session.py           — session lifecycle, Docker container + volume management
  reaper.py            — cleanup policies (timeout, count, space)
  mcp.py               — MCP server config, scope resolution, tool filtering
  mcp_proxy.py         — SSE proxy for outside-container MCPs + tool filtering

llmings/claude_chat/       ← EXTENSION (Claude-specific)
  __init__.py          — package marker
  __main__.py          — CLI entry point (argparse + session management)
  chat.py              — main chat loop, _build_args(), local vs container
  stream.py            — stream-json parser (yields text/meta from Popen)
  typewriter.py        — adaptive display engine (reader thread + drain)
  auth.py              — macOS Keychain extraction (OAuth token)
  Dockerfile           — layered sandbox image (base → Claude CLI → user)
  tests/               — extension-specific tests (14)

tests/                             ← CORE TESTS (run with main suite)
  test_sandbox.py      — 22 session lifecycle tests
  test_sandbox_reaper.py — 11 cleanup policy tests
  test_sandbox_mcp.py  — 21 MCP config/filter tests
  test_sandbox_mcp_proxy.py — 11 SSE proxy integration tests
```

## Data Flow (Single Turn)

```mermaid
flowchart TD
    A[User input] --> B["chat.py: _build_args()"]
    B --> C{Runtime mode?}
    C -->|local| D["subprocess.Popen(['claude', *args])"]
    C -->|container| E["docker exec claude-chat-sandbox claude args"]
    D --> F["Popen with stdout=PIPE"]
    E --> F
    F --> G["typewriter() spawns reader thread"]
    G --> H["Reader thread: stream_response()"]
    G --> I["Main thread: drain deque at 300–4000 cps"]
    H -->|"text chunks"| J[(deque)]
    J --> I
    H -->|meta| K["session_id + cost"]
```

## Container Architecture

```mermaid
flowchart TB
    subgraph Host ["Host (macOS / Linux)"]
        Chat["chat.py main loop"]
        KC["Keychain → OAuth token"]
        Mgr["SessionManager"]
        KC --> Chat
        Chat --> Mgr

        subgraph Container ["Docker: ohsb-&lt;session_id&gt;"]
            User["User: sandbox (non-root)"]
            Key["ANTHROPIC_API_KEY=sk-ant-..."]
            Vol["Volume: ohvol-&lt;id&gt; → /workspace"]
            Claude["claude -p --bare\n--mcp-config ...\n--disallowedTools ..."]
        end

        subgraph Proxy ["MCP Proxies (if needed)"]
            SSE["SSE Proxy :PORT\n+ tool filtering"]
            MCP["MCP Server (stdio)"]
            SSE <-->|stdio| MCP
        end

        Chat -->|"session.exec_streaming()"| Claude
        Claude <-->|"host.docker.internal"| SSE
    end
```

## Multi-Node Architecture

```mermaid
flowchart LR
    subgraph Mac ["Controller (Mac)"]
        CY["cluster.yaml"]
        MB["Message Bus"]
        BT["Budget Tracker"]
        AA["Audit Aggregator"]
        subgraph CA ["Agent A"]
            direction TB
            A1["container"]
        end
    end

    subgraph Pi ["Worker (Pi)"]
        NY["node.yaml"]
        AE["Agent Executor"]
        LB["Local Budget Cap"]
        subgraph CB ["Agent B"]
            direction TB
            B1["container"]
        end
    end

    MB <-->|"WS tunnel"| AE
```

!!! info "Connection direction"
    The controller connects TO the worker, never the reverse.
    Auth uses pre-shared connection keys per node.
    All messages route through the controller's message bus.

## Cross-Node Message Flow

```mermaid
sequenceDiagram
    participant A as Agent A (Mac)
    participant C as Controller
    participant W as Worker (Pi)
    participant B as Agent B (Pi)

    A->>C: send_message(to="B")
    C->>C: Permission check
    C->>W: agent_message (via tunnel)
    W->>W: Permission check
    W->>B: Inject message
    B->>W: Response
    W->>C: Response
    C->>A: Delivered
```

## How It Builds on openhort

| openhort component | Role in agent framework |
|-------------------|------------------------|
| `hort/containers/base.py` | ContainerProvider ABC for sandboxes |
| `hort/containers/docker.py` | Docker-based agent execution |
| `hort/ext/plugin.py` | PluginContext for agent state |
| `hort/ext/mcp.py` | MCPMixin for agent capabilities |
| `hort/ext/connectors.py` | Task submission (Telegram, web) |
| `hort/ext/scheduler.py` | Health checks, timeout enforcement |
| `hort/ext/store.py` | Task state, execution logs |
| `hort/targets.py` | TargetRegistry for running agents |
| `hort/access/tokens.py` | Agent API authentication |
| `hort/access/tunnel_client.py` | Multi-node tunnel protocol |
| `hort/config.py` | Agent configuration persistence |

## Key Interfaces (Planned)

```python
class ModelProvider(ABC):
    def send(self, message, *, session_id=None) -> AgentTurn
    def stream(self, message, *, session_id=None) -> Generator
    def supports_tools(self) -> bool

class ToolPermissions:
    def is_allowed(self, tool_name: str) -> bool

class CommandFilter:
    def check(self, command: str) -> tuple[bool, str]

class BudgetState:
    def check(self, limits: BudgetLimits) -> str | None
```

!!! tip "Full interface definitions"
    See `subprojects/claude_chat/CONCEPT.md` for complete interface
    specs including all data classes and enums.
