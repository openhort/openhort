# Chat Debug API

Debug endpoints for the AI chat backend. Send messages, inspect tool calls,
diagnose why the AI behaves unexpectedly.

## REST Endpoint

### `POST /api/llmings/llming-wire/debug`

Send a message through the full chat pipeline (same container, same MCP
bridge as normal messages) and get a full debug trace.

```bash
curl -X POST http://localhost:8940/api/llmings/llming-wire/debug \
  -H 'Content-Type: application/json' \
  -d '{"text": "take a screenshot", "cid": "debug"}'
```

**Request:**

| Field | Type   | Default   | Description                       |
|-------|--------|-----------|-----------------------------------|
| text  | string | required  | Message to send to the AI         |
| cid   | string | `"debug"` | Conversation ID (isolates sessions) |

**Response:**

```json
{
  "result": "Here's your screen — a 3440x1440 ultrawide...",
  "exit_code": 0,
  "elapsed_s": 14.07,
  "tools": [
    {
      "name": "list_windows",
      "full_name": "mcp__openhort__list_windows",
      "input": {},
      "ts": 2.55
    },
    {
      "name": "screenshot",
      "full_name": "mcp__openhort__screenshot",
      "input": {"target": "desktop", "grid": true},
      "ts": 4.54
    }
  ],
  "events": [
    {"ts": 0.71, "type": "init", "session_id": "1db91..."},
    {"ts": 2.55, "type": "tool_call", "tool": "list_windows", "input": {}},
    {"ts": 4.54, "type": "tool_call", "tool": "screenshot", "input": {...}},
    {"ts": 13.5, "type": "text", "text": "Here's your screen..."},
    {"ts": 14.0, "type": "result", "text_len": 441, "cost_usd": 0.02}
  ],
  "session_id": "1db91b51-586d-48ac-b658-7b53157a1777"
}
```

**Response fields:**

| Field      | Description                                          |
|------------|------------------------------------------------------|
| result     | Final AI text response (base64 images stripped)      |
| exit_code  | Claude CLI exit code (0 = success)                   |
| elapsed_s  | Total wall time in seconds                           |
| tools      | List of tool calls with name, input, and timestamp   |
| events     | Full event stream (init, tool calls, text, result)   |
| session_id | Claude session ID (for `--resume`)                   |

## WS Commands

All commands go through the authenticated control WebSocket.

### `wire.send`

Same as the REST endpoint but via WebSocket.

```json
{"type": "wire.send", "text": "take a screenshot", "cid": "debug"}
```

### `wire.status`

Check chat backend status.

```json
{"type": "wire.status"}
```

Returns bridge status, active sessions, and system prompt length.

### `wire.reset`

Reset a chat session (clear conversation history).

```json
{"type": "wire.reset", "cid": "debug"}
```

## Diagnosing Tool Failures

When the AI says "tools are offline" but the server logs show tool calls succeeding:

1. **Send via debug API** — see exactly what tools the AI calls and what it receives
2. **Check tool names** — the AI might call shortened names that don't resolve
3. **Check response size** — large images (>1MB base64) can cause issues
4. **Check exit code** — non-zero means the Claude CLI crashed
5. **Check events** — look for errors between tool_call and result events

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| AI says "tools offline" but tools work | Tool names don't match (namespace issue) | Check `tools[].full_name` matches MCP tool list |
| exit_code=1, no result | Auth error or container issue | Check `/api/debug/chat` for auth errors |
| Tool called but no result event | Tool response too large or timeout | Reduce screenshot quality/resolution |
| Empty tools list | MCP bridge not connected | Check `wire.status` for bridge_running |
