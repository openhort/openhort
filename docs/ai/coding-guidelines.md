# Coding Guidelines

Rules for all code in openhort and its libraries (llming-com, etc.).

## Python Style

### Always use type annotations

Every function, method, parameter, and return value MUST have type annotations. No exceptions.

```python
# BAD
def get_metrics(self, data):
    cpu = data.get("cpu")
    return {"cpu": cpu}

# GOOD
def get_metrics(self, data: dict) -> dict:
    cpu: float = data.get("cpu", 0.0)
    return {"cpu": cpu}

# GOOD — callbacks with dict
@power("status")
async def get_status(self, data: dict) -> dict:
    ...

# GOOD — callbacks with Pydantic (framework auto-converts)
@power("status")
async def get_status(self, data: StatusRequest) -> StatusResponse:
    ...
```

### Callback data convention

All callbacks (powers, pulses, streams) take `self` + one data parameter. Never multiple positional args.

**Transport is always dict/JSON.** The framework auto-converts between dict and Pydantic models based on the type annotation:

- Annotated as `dict` → passed as-is
- Annotated as `BaseModel` subclass → framework parses `Model(**dict)` before calling
- Return annotated as `BaseModel` → framework calls `.model_dump()` before sending

```python
# Both are valid — transport is identical (JSON dict on the wire)
@pulse("alert")
async def on_alert(self, data: dict) -> None: ...

@pulse("alert")
async def on_alert(self, data: AlertEvent) -> None: ...  # AlertEvent is a Pydantic model
```

### No private attribute access from outside the class

Never access `_private` attributes on objects you don't own. Use public properties or methods.

```python
# BAD
value = manager._auth.auth_cookie_name
manager._registry.get_session(sid)

# GOOD
value = manager.auth.auth_cookie_name
entry = manager.resolve(request)
```

If a public API doesn't exist, add one to the class — don't reach into internals.

### No if/elif chains for dispatch

Use dictionaries for routing, dispatch tables, or registry patterns.

```python
# BAD
if msg_type == "list":
    await handle_list()
elif msg_type == "get":
    await handle_get()
elif msg_type == "set":
    await handle_set()

# GOOD
_HANDLERS = {
    "list": handle_list,
    "get": handle_get,
    "set": handle_set,
}
handler = _HANDLERS.get(msg_type)
if handler:
    await handler()
```

For WebSocket messages, use `WSRouter` with namespaced types (`llmings.list`, `config.get`).

### Configuration over hardcoding

Services that may run alongside other instances must accept configuration for names, ports, prefixes — not hardcode them.

```python
# BAD — cookie name hardcoded, collides with other apps
AUTH_COOKIE = "llming_auth"

# GOOD — configurable per app
class AuthManager:
    def __init__(self, *, app_name: str = ""):
        prefix = app_name or "llming"
        self.auth_cookie_name = f"{prefix}_auth"
```

### No blocking the event loop

Every subprocess call, Docker exec, file I/O, and network call MUST use `await loop.run_in_executor()` or native async I/O. One blocking call can hang the entire server.

### Error handling

- Never expose internal errors to users (stack traces, file paths, container IDs)
- Log the full error, return a safe generic message
- Use `try/except` at system boundaries, not around every line

### Naming

- Llmings (extensions): `LlmingBase`, `get_powers()`, `get_pulse()`, `execute_power()`
- WS commands: dot-namespaced (`llmings.list`, `config.get`, `credentials.status`)
- API routes: `/api/llmings/`, not `/api/plugins/`
- Files: `manifest.json` (not `extension.json`), `cards.js` (not `panel.js`)
- Class-level type annotations use `ClassVar[]` or are instance-level in `__init__`

## JavaScript Style

- No markdown in chat responses (mobile messaging context)
- Use `sendControlRequest({type: 'llmings.list'})` for data, not `fetch('/api/...')`
- REST fetch only for: session creation (`POST /api/session`) and binary data

## Architecture

### WebSocket-first

All sensitive operations go through the authenticated control WebSocket. REST endpoints exist for admin/external API use only and are protected by auth middleware.

### Llming isolation

Llmings never import each other directly. Communication goes through the message bus (`call`, `read_pulse`, `subscribe`).

### Native memory safety (macOS)

Every Quartz capture MUST be wrapped in `objc.autorelease_pool()`. Never use `CGBitmapContextCreate`. Never run the full test suite with `--cov=hort` or in background.
