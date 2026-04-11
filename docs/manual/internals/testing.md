# Testing

## Running Tests

```bash
# Run specific test files (preferred — fast, safe)
poetry run pytest tests/test_foo.py -v

# Run the full suite WITHOUT coverage
poetry run pytest tests/ -x -q --ignore=tests/test_ui_playwright.py

# Playwright UI tests (integration, skipped by default)
poetry run pytest tests/test_ui_playwright.py -m integration
```

!!! danger "Never run full coverage casually"
    `--cov=hort` force-imports every module including Quartz/pyobjc.
    Native `CFData` from `CGDataProviderCopyData` leaks 10–50 MB per
    frame. A single coverage run can consume 10+ GB. Only run when
    explicitly requested.

    ```bash
    # Coverage — only when explicitly needed
    poetry run pytest tests/ --cov=hort
    ```

## Test API Keys

The `.env` file contains `TEST_ANTHROPIC_API_KEY` — a low-tier key
for unit tests that need the Claude API.

```python
import os

api_key = os.environ["TEST_ANTHROPIC_API_KEY"]
```

!!! warning "Test key only"
    This key is for unit tests only. **Never** use it for:

    - Production or user-facing features
    - Sandbox containers (use OAuth from OS Keychain instead)
    - Load testing or high-volume calls
    - Anything committed to code or logs

## Chat Debug API

The Wire llming exposes a debug endpoint for testing the full AI chat
pipeline — same container, same MCP bridge, same credentials as real
messages.

### REST

```bash
curl -X POST http://localhost:8940/api/llmings/llming-wire/debug \
  -H 'Content-Type: application/json' \
  -d '{"text": "take a screenshot", "cid": "test1"}'
```

### Response

```json
{
  "result": "Here's your screen — a 3440x1440 ultrawide...",
  "exit_code": 0,
  "elapsed_s": 9.81,
  "tools": [
    {"name": "screenshot", "full_name": "mcp__openhort__screenshot",
     "input": {}, "ts": 4.54}
  ],
  "events": [
    {"ts": 0.7, "type": "init", "session_id": "..."},
    {"ts": 4.5, "type": "tool_call", "tool": "screenshot", "input": {}},
    {"ts": 9.1, "type": "text", "text": "Here's your screen..."},
    {"ts": 9.5, "type": "result", "text_len": 441, "cost_usd": 0.02}
  ],
  "session_id": "1db91b51-..."
}
```

### WS Commands

| Command | Description |
|---------|-------------|
| `wire.send` | Send message, get full debug trace |
| `wire.status` | Check bridge, sessions, prompt size |
| `wire.reset` | Reset a chat session |

### Diagnosing Tool Failures

| Symptom | Check |
|---------|-------|
| AI says "tools offline" but server logs show calls | `tools[].full_name` — wrong namespace? |
| `exit_code: 1`, no result | Auth error or `--mcp-config` arg parsing |
| Tool called but empty result | Response too large or timeout |
| Empty tools list | MCP bridge dead — check `wire.status` |
| Tools work in debug but not in Wire UI | Stale session — `/new` to reset |

## Playwright

Use Playwright for visual verification of the UI. Headless by default.

```bash
# Quick smoke test
LLMING_AUTH_SECRET=openhort-dev poetry run python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('http://localhost:8940/')
    page.wait_for_load_state('networkidle')
    page.screenshot(path='/tmp/smoke.png')
    browser.close()
"
```

!!! note
    xterm.js keyboard input doesn't work in headless Playwright
    (canvas-based rendering). Use Playwright for visual checks; use
    the Chrome MCP tools or a real browser for interactive terminal testing.

## Claude Code CLI Gotchas

When building tests that invoke `claude` CLI:

- **`--mcp-config` is variadic** — the message MUST come after `--`:
  `claude -p --mcp-config config.json -- "message"`
- **MCP failures are session-sticky** — if MCP fails on init, `--resume`
  keeps it failed. Always test with fresh sessions.
- **`--bare` does not disable MCP** — it disables hooks, keychain, and
  CLAUDE.md discovery. MCP still works via `--mcp-config`.
