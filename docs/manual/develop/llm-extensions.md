# LLM Extensions

Multi-provider LLM integration with two execution models, unified
conversation history, API key isolation, and MCP tool support.

## Provider Types

```mermaid
flowchart LR
    subgraph Framework ["hort/llm/ — Core Framework"]
        LP["LLMProvider (ABC)"]
        LP --> CLI["CLIProvider"]
        LP --> API["APIProvider"]
        API --> Store["ConversationStore"]
    end

    subgraph Extensions ["llmings/llms/"]
        CLI --> CC["claude_code\nClaudeCodeProvider"]
        API --> LA["llming_api\nLlmingProvider"]
        CLI -.-> CX["codex (future)"]
        API -.-> OA["openai (future)"]
    end
```

### CLI Providers

Executable LLMs that run as subprocesses. They manage their own
conversation state — we just manage the process lifecycle.

| Property | Detail |
|----------|--------|
| Examples | Claude Code, Codex, aider |
| Execution | subprocess (local temp dir or sandbox container) |
| History | Owned by the tool (e.g. `claude --resume`) |
| Cleanup | Reaper destroys sandbox session + volume |

### API Providers

SDK-bound LLMs called via HTTP. We own the conversation history
and replay it on resume.

| Property | Detail |
|----------|--------|
| Examples | Anthropic API, OpenAI API, Mistral, Google Gemini |
| Execution | In-process (local) or inside container |
| History | `ConversationStore` — JSON files with timeout cleanup |
| Cleanup | `store.cleanup_expired()` + reaper for containers |

## Execution Modes

Both provider types support local and container execution:

```mermaid
flowchart TD
    subgraph Local ["Local Mode"]
        L_LLM["LLM runs in-process\nor as local subprocess"]
        L_MCP["MCP servers\n(direct stdio)"]
        L_Store["~/.openhort/conversations/\n(JSON files)"]
        L_LLM --> L_MCP
        L_LLM --> L_Store
    end

    subgraph Container ["Container Mode"]
        subgraph Docker ["Docker: ohsb-<id>"]
            C_LLM["LLM process"]
            C_MCP_IN["Inside MCPs\n(stdio)"]
            C_LLM --> C_MCP_IN
        end

        C_Proxy["SSE Proxy\non host :PORT"]
        C_MCP_OUT["Outside MCPs\n(host stdio)"]
        C_MCP_OUT <-->|stdio| C_Proxy
        C_LLM <-->|"SSE via\nhost.docker.internal"| C_Proxy
    end
```

## API Key Isolation

```mermaid
sequenceDiagram
    participant Host as Host Process
    participant Docker as Docker Daemon
    participant Main as LLM Process
    participant MCP as MCP Server

    Host->>Docker: docker run -d (NO secrets in env)
    Note over Docker: Container starts<br/>with empty env

    Host->>Docker: docker exec -e API_KEY=sk-... python3 llm.py
    Docker->>Main: spawns process with API_KEY in env
    Note over Main: API_KEY visible only<br/>to this PID

    Main->>MCP: spawn MCP server (child process)
    Note over MCP: MCP inherits Main's env?

    Note over Host: Defense layers:<br/>1. secret_env excluded from docker run<br/>2. secret_env excluded from metadata JSON<br/>3. /proc/1/environ has NO key<br/>4. docker inspect shows NO key
```

### How `secret_env` works

```python
# Session creation — key NOT in docker run env
session = mgr.create(SessionConfig(
    image="openhort-sandbox-claude:latest",
    secret_env={"ANTHROPIC_API_KEY": "sk-..."},  # injected per-exec
    env={"SAFE_VAR": "visible"},                  # in container env
))
```

**Three isolation guarantees:**

1. **Not in `docker run`** — `_build_run_cmd()` only includes `env`,
   never `secret_env`. The container's global environment has no key.

2. **Not on disk** — `secret_env` has `exclude=True` in the Pydantic
   model. It's never written to the session metadata JSON file.

3. **Per-process injection** — `_exec_prefix()` adds
   `docker exec -e KEY=VAL` only for the spawned process. The key
   lives in that process's environment, not in `/proc/1/environ`.

!!! warning "MCP limitation"
    MCP servers spawned as child processes of the LLM process
    inherit its environment (standard Unix behavior). Full isolation
    from MCPs requires running MCPs as separate `docker exec`
    processes or using the outside-container proxy (which runs on
    the host and never sees the key).

## Conversation Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created: store.create()
    Created --> Active: send() / stream()
    Active --> Active: add messages
    Active --> Resumed: new provider + same conv_id
    Resumed --> Active: send(conversation_id=id)
    Active --> Destroyed: cleanup() or expired
    Destroyed --> [*]

    note right of Active
        Messages persisted as JSON
        in ~/.openhort/conversations/
    end note

    note right of Resumed
        History replayed into
        new LLM session
    end note
```

### Resume across process restarts

API providers replay stored history into a fresh LLM session:

```mermaid
sequenceDiagram
    participant P1 as Provider (original)
    participant Store as ConversationStore
    participant P2 as Provider (resumed)
    participant API as LLM API

    P1->>Store: add_message(user, "Remember 42")
    P1->>API: chat("Remember 42")
    API-->>P1: "I'll remember 42"
    P1->>Store: add_message(assistant, "I'll remember 42")
    Note over P1: Process exits

    Note over P2: New process starts

    P2->>Store: get_messages(conv_id)
    Store-->>P2: [user: "Remember 42", assistant: "I'll remember 42"]
    Note over P2: Replay history into<br/>fresh LLM session
    P2->>API: chat("What number?", history=[...])
    API-->>P2: "42"
    P2->>Store: add_message(assistant, "42")
```

## Cleanup Policies

```mermaid
flowchart TD
    Cleanup["--cleanup"]
    Cleanup --> Sessions["Sandbox Reaper"]
    Cleanup --> Convos["ConversationStore"]

    Sessions --> Expired["reap_expired()\ntimeout per session"]
    Sessions --> Count["reap_by_count()\nmax 20 sessions"]
    Sessions --> Space["reap_by_space()\nmax 5 GB volumes"]

    Convos --> CExpired["cleanup_expired()\ntimeout per conversation"]

    Expired -->|destroy| Docker["Container + Volume"]
    CExpired -->|delete| JSON["Conversation JSON"]
```

Both cleaners run automatically on startup and can be triggered
manually via `--cleanup`.

## Docker Layer Strategy

```mermaid
flowchart TB
    subgraph Base ["openhort-sandbox-base (hort/sandbox/Dockerfile)"]
        B1["node:22-slim + system packages"]
        B2["sandbox user + /workspace"]
        B1 --> B2
    end

    subgraph Claude ["openhort-sandbox-claude"]
        C1["FROM base"]
        C2["npm install claude-code"]
        C1 --> C2
    end

    subgraph Llming ["openhort-sandbox-llming"]
        L1["FROM base"]
        L2["pip install llming-models"]
        L1 --> L2
    end

    Base --> Claude
    Base --> Llming
```

Each extension adds only its specific tools on top of the shared
base image. The base layer (~200 MB) is cached and shared.

## CLI Reference

### Claude Code (`llmings.llms.claude_code`)

```bash
poetry run python -m llmings.llms.claude_code
poetry run python -m llmings.llms.claude_code -c --memory 1g
poetry run python -m llmings.llms.claude_code -c --session <id>
poetry run python -m llmings.llms.claude_code --mcp "fs=npx ..."
```

### llming API (`llmings.llms.llming_api`)

```bash
# Local mode (API key from env)
poetry run python -m llmings.llms.llming_api -m claude_haiku

# Container mode (key isolated via secret_env)
poetry run python -m llmings.llms.llming_api -c --api-key sk-...

# Resume conversation
poetry run python -m llmings.llms.llming_api --conversation <id>

# Container + MCP
poetry run python -m llmings.llms.llming_api -c \
  --mcp "db=npx -y @anthropic/mcp-postgres"

# Management
poetry run python -m llmings.llms.llming_api --list-conversations
poetry run python -m llmings.llms.llming_api --list-sessions
poetry run python -m llmings.llms.llming_api --cleanup
```

## Module Structure

```
hort/llm/                                  Core framework
  base.py           LLMProvider, LLMMessage, LLMChunk, LLMResponse
  cli_provider.py   CLIProvider — subprocess-based LLMs
  api_provider.py   APIProvider — SDK-based LLMs + ConversationStore
  history.py        ConversationStore — JSON conversation persistence

hort/sandbox/                              Core infrastructure
  session.py        Session (secret_env isolation), SessionManager
  reaper.py         Timeout / count / space cleanup
  mcp.py            MCP config + tool filtering
  mcp_proxy.py      SSE proxy for outside-container MCPs
  Dockerfile        Base sandbox image

llmings/llms/claude_code/          Claude Code CLI
  provider.py       ClaudeCodeProvider(CLIProvider)
  Dockerfile        FROM base + claude-code

llmings/llms/llming_api/           llming-models SDK
  provider.py       LlmingProvider(APIProvider)
  container_entry.py  In-container entrypoint (streams JSON)
  Dockerfile        FROM base + llming-models
```

## Test Coverage

| Test | Count | What |
|------|-------|------|
| Core sandbox | 27 | Session lifecycle, secret_env, reaper |
| Core MCP | 32 | Config, proxy, SSE, tool filtering |
| Core LLM history | 11 | CRUD, timeout cleanup, resume |
| Claude Code ext | 14 | Auth, stream parser, typewriter |
| llming API ext | 9 | Real API calls, multi-turn, resume, secret isolation |
