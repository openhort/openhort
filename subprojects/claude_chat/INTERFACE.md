# Claude Chat — Interface Documentation

Terminal chat interface that wraps Claude Code CLI, hiding all
protocol details behind a simple conversational UX. Supports
running locally or inside a Docker sandbox container.

## Running

```bash
# Local mode (default) — Claude runs on your machine
poetry run python -m subprojects.claude_chat
poetry run python -m subprojects.claude_chat --model sonnet
poetry run python -m subprojects.claude_chat --system "You are a pirate"
poetry run python -m subprojects.claude_chat -m haiku -s "Be concise"

# Container mode — Claude runs inside a Docker sandbox
poetry run python -m subprojects.claude_chat --container
poetry run python -m subprojects.claude_chat -c --model sonnet
```

## Modes of Operation

### Local Mode (default)

Claude runs directly on the host machine as a subprocess. Each
user message spawns `claude -p --dangerously-skip-permissions ...`
in a temporary directory. Auth uses whatever the host has configured
(OAuth via Keychain, API key, etc.).

### Container Mode (`--container` / `-c`)

Claude runs inside a Docker container (`claude-chat-sandbox`).
This provides a controlled, isolated environment where Claude has
dangerous-mode permissions but can only affect the container
filesystem. The host is never touched.

## Container Mode — Detailed Walkthrough

### Step 1: Auth Extraction from macOS Keychain

Claude Code stores OAuth credentials in the macOS Keychain under
the service name `Claude Code-credentials`. The entry is a JSON
blob containing an OAuth access token, refresh token, expiry, and
subscription metadata.

**How it's read:**

```python
raw = subprocess.check_output(
    ["security", "find-generic-password",
     "-s", "Claude Code-credentials", "-w"],
    stderr=subprocess.DEVNULL, text=True,
).strip()
creds = json.loads(raw)
token = creds["claudeAiOauth"]["accessToken"]
```

The `security` command is macOS-specific (`/usr/bin/security`).
It reads from the user's login keychain without requiring a
password prompt (the keychain is unlocked while the user is
logged in).

**Keychain entry structure:**

```json
{
  "claudeAiOauth": {
    "accessToken": "sk-ant-oat01-...",
    "refreshToken": "sk-ant-ort01-...",
    "expiresAt": 1774529896836,
    "scopes": [
      "user:file_upload",
      "user:inference",
      "user:mcp_servers",
      "user:profile",
      "user:sessions:claude_code"
    ],
    "subscriptionType": "max",
    "rateLimitTier": "default_claude_max_20x"
  }
}
```

**Key discovery:** The OAuth access token (`sk-ant-oat01-...`)
works directly as `ANTHROPIC_API_KEY` when Claude CLI is run
with `--bare` mode. The `--bare` flag tells Claude to skip
keychain reads and use `ANTHROPIC_API_KEY` exclusively. This
means no login or auth setup is needed inside the container.

**Token lifetime:** The `expiresAt` field is a Unix timestamp
in milliseconds. When the container is stopped and restarted,
the token is re-extracted from the Keychain (which may have been
refreshed by the host Claude session). If a container is
already running, the existing token is kept.

### Step 2: Docker Image Build

The sandbox image is built from `subprojects/claude_chat/Dockerfile`
on first use. Subsequent runs reuse the cached image.

**Dockerfile contents:**

```dockerfile
FROM node:22-slim

# Tools: git, curl, jq, python3, build-essential
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq python3 python3-pip build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (npm global install)
RUN npm install -g @anthropic-ai/claude-code

# Non-root user — required because --dangerously-skip-permissions
# refuses to run as root for security reasons
RUN useradd -m -s /bin/bash claude
RUN mkdir -p /workspace && chown claude:claude /workspace
USER claude
WORKDIR /workspace

CMD ["sleep", "infinity"]
```

**Why non-root:** Claude Code's `--dangerously-skip-permissions`
flag explicitly blocks execution under root/sudo. The `claude`
user is a regular unprivileged user inside the container.

**Why `sleep infinity`:** The container stays alive between chat
turns. Each turn runs `docker exec` to invoke Claude inside the
already-running container. This means:
- Claude's session store persists between turns (`--resume` works)
- Files created by Claude persist across the conversation
- No container startup overhead per message

### Step 3: Container Lifecycle

```python
def ensure_container(token: str) -> None:
    if container_running():
        return                          # Already up, reuse it
    if container_exists():
        docker rm -f claude-chat-sandbox  # Stopped — recreate (fresh token)
    docker run -d \
        --name claude-chat-sandbox \
        -e ANTHROPIC_API_KEY=<token> \
        claude-chat-sandbox:latest
```

The token is passed as an environment variable at container
creation time. It is NOT written to any file — it exists only
in the container's environment.

### Step 4: Command Execution Per Turn

Each chat message runs Claude inside the container via `docker exec`:

```bash
docker exec -i claude-chat-sandbox \
    claude -p \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    --dangerously-skip-permissions \
    --bare \
    [--model MODEL] \
    [--resume SESSION_ID] \
    "user message here"
```

The `-i` flag keeps stdin open (required by the subprocess pipe).
stdout is piped back to the host for stream parsing.

**Why `--bare` in container mode only:** Inside the container
there is no keychain, no hooks, no LSP, no MCP servers, no
CLAUDE.md files. The `--bare` flag tells Claude to skip all of
these and authenticate strictly via `ANTHROPIC_API_KEY`. In local
mode, `--bare` is NOT used so the full Claude experience (hooks,
MCP, etc.) is preserved.

### Step 5: Stream Parsing and Display

The stdout pipe from `docker exec` carries the same stream-json
format as a local `claude -p` process. The stream parser and
typewriter engine are shared between local and container modes —
no code duplication.

## Architecture

```
┌──────────────┐     stdin      ┌──────────────────────────┐
│  User types  │ ──────────────>│  chat.run_chat()         │
│  in terminal │                │   builds CLI args        │
└──────────────┘                │   dispatches to runner   │
       ▲                        └──────────┬───────────────┘
       │                                   │
       │ stdout                  ┌─────────┴──────────┐
       │ (typewriter)            │  local?  container? │
       │                         └──┬─────────┬───────┘
┌──────┴───────┐                    │         │
│  Typewriter   │       subprocess.Popen  docker exec
│  (main thread)│           │         │
└──────┬───────┘            ▼         ▼
       │              ┌──────────────────────────┐
       └── deque ─────│  stream.stream_response()│
                      │  (reader thread)         │
                      └──────────────────────────┘
```

Both modes produce a `subprocess.Popen` with a stdout pipe.
The stream parser and typewriter are mode-agnostic — they only
care about the pipe, not how it was created.

### Data flow per turn

1. User types a message at the `you>` prompt
2. `chat.py` builds the `claude -p` argument list via `_build_args()`
3. In local mode: `subprocess.Popen(["claude", *args])` directly
4. In container mode: `container.exec_claude(args)` wraps it as
   `docker exec claude-chat-sandbox claude <args>`
5. Both return a `Popen[bytes]` with `stdout=PIPE`
6. `typewriter()` spawns a reader thread that calls `stream_response(proc)`
7. `stream_response()` reads lines via `proc.stdout.readline()`,
   parses JSON, yields `("text", chunk)` and `("meta", dict)` events
8. The reader thread pushes characters into a `deque`
9. The main thread pops characters at an adaptive rate (300–4000 cps)
   and writes them to stdout
10. After the stream ends, remaining buffer is flushed within 2 seconds
11. The `meta` event provides `session_id` (for `--resume` next turn)
    and `cost` (for the running total)

## Claude CLI Flags Used

| Flag | Purpose | Mode |
|------|---------|------|
| `-p` / `--print` | Non-interactive mode, exit after response | Both |
| `--output-format stream-json` | Newline-delimited JSON events on stdout | Both |
| `--verbose` | Required by stream-json | Both |
| `--include-partial-messages` | Emit `content_block_delta` events as they arrive | Both |
| `--dangerously-skip-permissions` | Bypass all tool permission prompts | Both |
| `--bare` | Skip hooks/keychain, use `ANTHROPIC_API_KEY` for auth | Container only |
| `--resume <id>` | Continue a previous conversation by session ID | Both |
| `--model <name>` | Override model (sonnet, opus, haiku) | Both |
| `--system-prompt <text>` | Replace default system prompt | Both |
| `--append-system-prompt <text>` | Append plain-text formatting instruction | Both (turn 0) |

## Stream-JSON Wire Protocol

Claude CLI with `--output-format stream-json --verbose --include-partial-messages`
emits one JSON object per line on stdout. Each line is self-contained
(no multi-line JSON). The protocol is identical for local and container
modes.

### Events we consume

#### 1. Init

```json
{"type": "system", "subtype": "init", "session_id": "uuid-here", "tools": [...], "model": "...", ...}
```

First event emitted. Provides the `session_id` used for `--resume`
on subsequent turns. Also contains model info, available tools,
and permission mode.

#### 2. Text delta

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

Incremental text fragment. Arrives as Claude generates tokens.
Multiple deltas concatenate to form the full response. The `index`
field identifies which content block this delta belongs to (a
single response can have multiple blocks, e.g. thinking + text).

#### 3. Result

```json
{
  "type": "result",
  "subtype": "success",
  "session_id": "uuid-here",
  "total_cost_usd": 0.037,
  "result": "full response text",
  "duration_ms": 2285,
  "num_turns": 1,
  "stop_reason": "end_turn",
  "usage": { ... }
}
```

Final event. Provides cost, session_id (fallback if init was
missed), and usage statistics. The `result` field contains the
complete response text (redundant with deltas, used as fallback).

### Events we skip

| Event type | Subtype/inner type | Why skipped |
|-----------|-------------------|-------------|
| `stream_event` | `content_block_delta` with `thinking_delta` | Internal reasoning, not shown to user |
| `stream_event` | `content_block_delta` with `signature_delta` | Cryptographic signature of thinking block |
| `stream_event` | `message_start` | Lifecycle marker, no user-facing content |
| `stream_event` | `message_stop` | Lifecycle marker |
| `stream_event` | `message_delta` | Stop reason/usage (captured from `result` instead) |
| `stream_event` | `content_block_start` | Block type announcement (we infer from deltas) |
| `stream_event` | `content_block_stop` | Block boundary marker |
| `assistant` | — | Full message snapshot (redundant with deltas) |
| `rate_limit_event` | — | Rate limit status, not user-facing |

### Error handling

- Malformed JSON lines are silently skipped
- Empty lines are silently skipped
- If no `session_id` appears in the `init` event, it's extracted
  from the `result` event as fallback
- If `stream_response()` yields no `text` events, the typewriter
  prints `(no response)`

## Typewriter Display Engine

The typewriter smooths output so it always feels like fast streaming,
regardless of whether Claude sends tokens one-at-a-time or in large
blocks.

### Problem

Claude's stream-json output arrives in unpredictable patterns:
- Sometimes token-by-token (small deltas, steady stream)
- Sometimes in large blocks (thinking completes, then text dumps)
- Sometimes with pauses (tool use, rate limiting)

Printing directly would alternate between trickle and wall-of-text.

### Solution

A producer-consumer pattern with adaptive rate control:

- **Reader thread (producer)**: calls `stream_response()`, pushes
  individual characters into a `collections.deque` (thread-safe
  for append/popleft).
- **Main thread (consumer)**: pops characters and writes to stdout
  at a rate determined by how full the buffer is.

### Speed adaptation algorithm

```python
pending = len(buf)
if pending > 80:
    cps = MAX_CPS                                          # 4000
elif pending > 20:
    cps = MIN_CPS + (MAX_CPS - MIN_CPS) * (pending - 20) / 60  # linear ramp
else:
    cps = MIN_CPS                                          # 300
```

| Buffer depth | CPS | Chunk size | Feel |
|-------------|-----|------------|------|
| 0–20 chars | 300 | 1 char | Natural streaming, keeping pace with live tokens |
| 20–80 chars | 300–4000 | 1 char | Accelerating to catch up |
| 80+ chars | 4000 | `pending // 40` | Fast multi-char bursts |

### Drain guarantee

Once the reader thread finishes (stream complete), any remaining
buffer must flush within `MAX_DRAIN_S` (2 seconds). The drain
loop calculates chunk sizes dynamically:

```python
elapsed = time.monotonic() - drain_start
remaining_time = max(MAX_DRAIN_S - elapsed, 0.01)
chunk_size = max(1, int(pending / (remaining_time * MAX_CPS)) + 1)
```

This means: if 1000 characters remain with 1 second left and
MAX_CPS is 4000, chunk_size = 1000 / (1.0 * 4000) + 1 = 1,
so it emits 1 char per tick at 4000 ticks/sec = done in 0.25s.
If 8000 characters remain with 0.5s left, chunk_size = 4, so
it emits 4 chars per tick = done in 0.5s.

### Constants

```python
MIN_CPS = 300       # chars/sec floor — never slower than this
MAX_CPS = 4000      # chars/sec ceiling — never faster than this
MAX_DRAIN_S = 2.0   # max seconds to flush remaining buffer after stream ends
```

### Leading newline handling

Claude sometimes starts its response with `\n\n`. The reader
thread strips leading newlines from the first text chunk so the
response starts on the same line as the `claude>` prompt.

## Container Details

| Property | Value |
|----------|-------|
| Container name | `claude-chat-sandbox` |
| Image name | `claude-chat-sandbox:latest` |
| Base image | `node:22-slim` (Debian bookworm) |
| Installed tools | git, curl, jq, python3, pip, build-essential, ca-certificates |
| Claude CLI | `@anthropic-ai/claude-code` (npm global, same version as host) |
| User | `claude` (UID 1000, non-root) |
| Working directory | `/workspace` |
| Auth mechanism | `ANTHROPIC_API_KEY` env var (OAuth token from host Keychain) |
| Session storage | `/home/claude/.claude/` inside the container |
| Persistence | Container stays alive between turns; destroyed on recreate |
| Network | Full network access (Claude needs to reach api.anthropic.com) |

### Managing the container

```bash
# Check if running
docker ps -f name=claude-chat-sandbox

# Inspect environment (verify token is set)
docker exec claude-chat-sandbox env | grep ANTHROPIC

# Shell into the container
docker exec -it claude-chat-sandbox bash

# Stop and remove
docker rm -f claude-chat-sandbox

# Rebuild image (e.g. after Dockerfile changes)
docker rmi claude-chat-sandbox:latest
# Next --container run will rebuild automatically

# View what Claude created inside
docker exec claude-chat-sandbox ls -la /workspace/
```

## Module Structure

```
subprojects/claude_chat/
  __init__.py          — package marker
  __main__.py          — CLI entry point (argparse: --model, --system, --container)
  chat.py              — main chat loop, _build_args(), dispatches local vs container
  stream.py            — stream-json parser (yields text/meta events from Popen stdout)
  typewriter.py        — adaptive typewriter display engine (reader thread + main thread)
  container.py         — Docker sandbox lifecycle:
                           get_oauth_token()    — macOS Keychain extraction
                           image_exists()       — check if Docker image is built
                           build_image()        — docker build
                           container_running()  — docker inspect state check
                           container_exists()   — docker inspect existence check
                           ensure_container()   — create + start if needed
                           stop_container()     — docker rm -f
                           exec_claude()        — docker exec, returns Popen
  Dockerfile           — sandbox image definition
  tests/
    test_stream.py     — 5 parser unit tests (text delta, thinking skip,
                         malformed lines, session ID fallback, unknown events)
    test_typewriter.py — 5 display unit tests (output, leading newlines,
                         no response, speed bounds, large block drain)
    test_container.py  — 11 container unit tests (token extraction success/
                         failure/bad JSON/missing key, image exists/not,
                         container running/not/missing, container exists/not)
  INTERFACE.md         — this file
```

## Testing

```bash
# All unit tests (21 tests, no network/Docker/Claude CLI needed)
poetry run pytest subprojects/claude_chat/tests/ -v

# Integration test only (requires Claude CLI + API access)
poetry run pytest subprojects/claude_chat/tests/ -v -m integration
```

## TODOs

### Cross-platform credential extraction

Currently `get_oauth_token()` only works on macOS (uses the
`security` CLI to read from the login Keychain). Needs backends for:

- **Linux**: Claude Code on Linux stores credentials via
  `libsecret` (GNOME Keyring / KDE Wallet) or possibly a
  plaintext fallback in `~/.claude/`. Need to investigate where
  Claude Code actually persists credentials on Linux and implement
  a `secret-tool` or file-based reader. Also need to check if
  Claude Code uses Electron `safeStorage` on Linux (which encrypts
  to a file using the OS keyring as the encryption key).

- **Windows**: Claude Code on Windows likely uses the Windows
  Credential Manager (via `dpapi` or the `wincred` store).
  Need to investigate the service name and implement extraction
  via `ctypes` calls to `CredReadW` or the `keyring` Python
  package.

- **Fallback**: Support `ANTHROPIC_API_KEY` env var as a direct
  override, skipping Keychain entirely. This would work on all
  platforms and in CI.

- **Architecture**: Refactor `get_oauth_token()` into a
  `CredentialProvider` interface with platform-specific
  implementations, auto-detected at runtime via `sys.platform`.

### Multi-provider support

Currently hardcoded to Docker. Should support:

- **Podman**: Drop-in Docker replacement. The CLI is largely
  compatible (`podman run`, `podman exec`), but some flags
  differ. Needs testing and possibly a `--runtime podman` flag.

- **Azure Container Instances**: For cloud-hosted sandboxes.
  Would use the existing `hort/containers/` provider abstraction
  and Azure CLI (`az container create/exec`). Relevant for
  remote access scenarios where no local Docker is available.

- **Kubernetes / k8s pods**: For environments where Docker isn't
  available but k8s is. Would use `kubectl run` / `kubectl exec`.

- **Architecture**: Refactor `container.py` into a
  `SandboxProvider` interface with `ensure()`, `exec()`, `stop()`
  methods. Implementations for Docker, Podman, ACI, k8s. The
  `--container` flag would become `--sandbox docker` (default),
  `--sandbox podman`, `--sandbox aci`, etc.

### Token refresh

The OAuth access token has an expiry (`expiresAt`). Currently:
- On container start, the token is extracted fresh from the Keychain
- If the container is already running, the old token is reused
- There is no mechanism to refresh the token mid-session

Needed:
- Check token expiry before each turn; if expired, re-extract
  from Keychain and update the container env var (requires
  container recreation or `docker exec -e` which doesn't exist —
  may need to write token to a file inside the container instead).
- Alternatively, use the `refreshToken` to obtain a new
  `accessToken` directly (requires knowledge of the Anthropic
  OAuth refresh endpoint).

### Container image versioning

Currently uses `claude-chat-sandbox:latest` with no version
tracking. If the Dockerfile changes, the user must manually
`docker rmi` the old image. Should:
- Hash the Dockerfile contents and include in the image tag
- Auto-rebuild when the Dockerfile changes
- Pin the Claude CLI version in the Dockerfile for reproducibility

### Security hardening

The container currently has full network access (required for
Claude to reach api.anthropic.com). Could be tightened:
- Restrict outbound network to only `api.anthropic.com`
  (Docker network policy or iptables rules inside the container)
- Mount `/workspace` as a tmpfs to prevent disk persistence
  between sessions (if desired)
- Add resource limits (memory, CPU) to prevent runaway processes
- Add `--read-only` root filesystem with explicit writable mounts

### Testing gaps

- **Container integration tests**: No automated tests that
  actually build the image and run Claude inside the container.
  Needs a `@pytest.mark.docker` marker and CI with Docker access.
- **Linux host testing**: The entire flow (Keychain extraction +
  Docker exec) has only been tested on macOS. Need to verify on
  Linux (where the Keychain part would need the Linux backend).
- **Windows host testing**: Untested. Docker Desktop on Windows
  uses WSL2 which should work for the container part, but
  credential extraction needs the Windows backend.
- **Token expiry testing**: No tests for expired token handling.
- **Network failure testing**: No tests for Docker not running,
  Docker daemon not responding, or network failures during
  `docker exec`.
- **Multi-turn resume in container**: Tested manually (2 turns)
  but no automated test that verifies `--resume` works across
  `docker exec` invocations.
