# Claude Chat — Interface Documentation

Terminal chat interface that wraps Claude Code CLI, hiding all
protocol details behind a simple conversational UX.

## Running

```bash
# Default (opus, no custom prompt)
poetry run python -m subprojects.claude_chat

# Pick a model
poetry run python -m subprojects.claude_chat --model sonnet

# Custom system prompt
poetry run python -m subprojects.claude_chat --system "You are a pirate"

# Both
poetry run python -m subprojects.claude_chat -m haiku -s "Be concise"
```

## Architecture

```
┌──────────────┐     stdin      ┌──────────────────────────┐
│  User types  │ ──────────────>│  chat.run_chat()         │
│  in terminal │                │   builds CLI command     │
└──────────────┘                │   spawns subprocess      │
       ▲                        └──────────┬───────────────┘
       │                                   │
       │ stdout                            │ stdout pipe
       │ (typewriter)                      ▼
┌──────┴───────┐                ┌──────────────────────────┐
│  Typewriter   │<───── deque ──│  stream.stream_response()│
│  (main thread)│               │  (reader thread)         │
└──────────────┘                └──────────────────────────┘
```

Each user message spawns a **new** `claude -p` subprocess.
Conversation state is maintained across turns by passing
`--resume <session_id>` to subsequent invocations. The session
is persisted by Claude Code itself (on disk), not by this app.

## Claude CLI Flags Used

| Flag | Purpose |
|------|---------|
| `-p` / `--print` | Non-interactive mode, exit after response |
| `--output-format stream-json` | Newline-delimited JSON events on stdout |
| `--verbose` | Required by stream-json |
| `--include-partial-messages` | Emit `content_block_delta` events as they arrive |
| `--dangerously-skip-permissions` | Bypass all tool permission prompts |
| `--resume <id>` | Continue a previous conversation by session ID |
| `--model <name>` | Override model (sonnet, opus, haiku) |
| `--system-prompt <text>` | Replace default system prompt |
| `--append-system-prompt <text>` | Append to system prompt (used for plain-text instruction) |

## Stream-JSON Wire Protocol

Claude CLI with `--output-format stream-json --verbose --include-partial-messages`
emits one JSON object per line. The events we consume:

### 1. Init

```json
{"type": "system", "subtype": "init", "session_id": "uuid-here", ...}
```

First event. Provides the `session_id` needed for `--resume`.

### 2. Text delta

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

Incremental text fragment. These arrive as Claude generates tokens.
Multiple deltas concatenate to form the full response.

### 3. Thinking delta (skipped)

```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_delta",
    "index": 0,
    "delta": {"type": "thinking_delta", "thinking": "..."}
  }
}
```

Internal reasoning. Silently discarded — not shown to user.

### 4. Result

```json
{
  "type": "result",
  "subtype": "success",
  "session_id": "uuid-here",
  "total_cost_usd": 0.037,
  "result": "full response text",
  ...
}
```

Final event. Provides cost and session_id (fallback if init was missed).

### Events we ignore

- `rate_limit_event` — rate limit status
- `stream_event` with `message_start`, `message_stop`, `message_delta`,
  `content_block_start`, `content_block_stop` — lifecycle markers
- `assistant` — full message snapshot (redundant with deltas)

## Typewriter Display Engine

The typewriter smooths output so it always feels like fast streaming,
regardless of whether Claude sends tokens one-at-a-time or in large blocks.

### Design

- **Reader thread**: consumes `stream_response()` events, pushes individual
  characters into a `deque`.
- **Main thread**: pops characters from the deque and writes them to stdout
  at an adaptive rate.

### Speed adaptation

| Buffer depth | Behavior |
|-------------|----------|
| < 20 chars | `MIN_CPS` (300 cps) — stream is arriving live |
| 20–80 chars | Linear ramp from 300 to 4000 cps |
| > 80 chars | `MAX_CPS` (4000 cps) + multi-char chunks |

### Drain guarantee

Once the stream ends (reader thread finishes), any remaining buffer is
flushed within `MAX_DRAIN_S` (2 seconds). The drain loop calculates
chunk sizes dynamically:

```
chunk_size = pending / (remaining_time * MAX_CPS) + 1
```

This ensures the last characters always arrive promptly, even for
very long responses that arrive as a single block.

### Constants

```python
MIN_CPS = 300       # chars/sec floor
MAX_CPS = 4000      # chars/sec ceiling
MAX_DRAIN_S = 2.0   # max seconds to flush after stream ends
```

## Module Structure

```
subprojects/claude_chat/
  __init__.py       — package marker
  __main__.py       — CLI entry point (argparse)
  chat.py           — main chat loop (input, spawn, display)
  stream.py         — stream-json parser (yields text/meta events)
  typewriter.py     — adaptive typewriter display engine
  tests/
    test_stream.py      — 5 parser unit tests
    test_typewriter.py  — 5 display unit tests
  INTERFACE.md      — this file
```

## Testing

```bash
# Unit tests (no network, no claude CLI needed)
poetry run pytest subprojects/claude_chat/tests/ -v

# Integration test (requires claude CLI + API access)
poetry run pytest subprojects/claude_chat/tests/ -v -m integration
```
