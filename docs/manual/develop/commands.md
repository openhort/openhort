# Commands & Powers

Every user-facing command is a Power on a llming. Connectors (Telegram,
Wire) are pure transport — they route commands to llmings via the
framework. No command logic lives in connector code.

## Defining Powers

Use the `@power` decorator on any method. The docstring IS the
description — first line for `/help`, rest for detailed docs.

```python
from hort.llming import Llming, power, PowerInput, PowerOutput

class SystemMonitor(Llming):
    @power("get_metrics")
    async def get_metrics(self) -> MetricsResponse:
        """Get current CPU, memory, and disk metrics.

        Returns real-time system metrics polled every 5 seconds.
        Includes per-core CPU if available.
        """
        return MetricsResponse(cpu=self._cpu)
```

### Description from docstring

The framework extracts two parts:

- **First line** — short description, shown in `/help` and MCP tool listings
- **After blank line** — long description, shown in detailed help and API docs

```python
@power("screenshot")
async def screenshot(self) -> ScreenshotResponse:
    """Capture a screenshot of the desktop or a specific window.

    For ultrawide displays, use grid=true first to see labeled cells
    (A1-D4), then grid_cell='B2' to zoom into the area you need.
    """
```

No `description=` parameter on the decorator. One source of truth.

## Slash Commands

Add `command=True` to make a power available as a `/command` in
Telegram, Wire, and other connectors. Only `command=True` powers
appear in `/help`.

```python
@power("cpu", command=True)
async def cpu_command(self) -> str:
    """Current CPU, memory, and disk usage."""
    return f"CPU: {self._cpu}%"
```

A command IS a power — same handler, same Pydantic model, two
input paths:

```
# As power (structured):
await self.llmings["system-monitor"].call("cpu")

# As command (positional string):
/cpu
```

## Subcommands

Use `sub=` for grouped commands. The root command shows clickable
links to all subcommands.

```python
@power("hort", command=True, admin_only=True)
async def hort_root(self) -> str:
    """Hort admin — manage containers, sessions, and workers."""
    # Shows when user types /hort with no subcommand
    ...

@power("hort", sub="info", command=True, mcp=False)
async def hort_info(self) -> str:
    """Show container and LLM executor status."""
    ...

@power("hort", sub="restart", command=True, mcp=False, admin_only=True)
async def hort_restart(self) -> str:
    """Restart all sandbox containers and clear chat sessions."""
    ...
```

### How it appears

`/help`:
```
/hort — Hort admin — manage containers, sessions, and workers.
```

`/hort` (clicked):
```
  ohsb-abc123: Up 2 hours (openhort-claude-code)

/hort__detail — Show detailed info for a specific container.
/hort__info — Show container and LLM executor status.
/hort__restart — Restart all sandbox containers.
/hort__sessions — List active chat sessions.
```

### Subcommand separator: `__`

Telegram doesn't support spaces in commands. Double underscore
is the separator:

| User types | Framework routes to |
|---|---|
| `/hort` | root power `"hort"` |
| `/hort info` | subcommand `"hort.info"` |
| `/hort__info` | same — `"hort.info"` (clickable in Telegram) |
| `/hort__detail abc` | `"hort.detail"` with args `"abc"` |

Works in all connectors (Telegram, Wire, future Discord/Slack).

## Pydantic Input Models

Powers can take typed input via Pydantic models. Positional args
from commands are mapped to fields in declaration order.

```python
from hort.llming import PowerInput
from pydantic import Field

class LightControl(PowerInput):
    light_id: str = Field(description="Light ID or name")
    brightness: int = Field(default=255, description="Brightness 0-255", ge=0, le=255)

@power("set_light", command=True)
async def set_light(self, req: LightControl) -> str:
    """Set a light's brightness."""
    ...
```

### Two input paths

```
# As power (structured dict):
await self.llmings["hue-bridge"].call("set_light", {"light_id": "1", "brightness": 200})

# As command (positional string → mapped to fields in order):
/set_light 1 200
# → LightControl(light_id="1", brightness=200)

/set_light 1
# → LightControl(light_id="1", brightness=255)  # default
```

The `version` field (from PowerInput base) is skipped during
positional mapping. Nested objects cannot be filled positionally —
call as a power with a dict for those.

## PowerOutput

Responses use HTTP-like status codes:

```python
from hort.llming import PowerOutput

class MetricsResponse(PowerOutput):
    version: int = 1
    cpu: float
    memory: float

# Success (default):
return MetricsResponse(cpu=42.0, memory=68.5)  # code=200

# Errors:
return PowerOutput(code=404, message="Sensor not found")
return PowerOutput(code=403, message="Admin only")
return PowerOutput(code=500, message="Hardware error")

# Check result:
result.ok      # True if 200 <= code < 300
result.code    # 200, 403, 404, 500, ...
```

## MCP Exposure

Every power is an MCP tool by default (`mcp=True`). AI agents
see all powers with their full descriptions and input schemas.

Set `mcp=False` to hide from AI:

```python
@power("hort", sub="restart", command=True, mcp=False, admin_only=True)
async def hort_restart(self) -> str:
    """Restart containers. Not callable by AI."""
```

## Admin-Only

`admin_only=True` restricts a command to admin users. The
connector checks user permissions before routing.

```python
@power("kill_process", command=True, admin_only=True)
async def kill_process(self, req: KillRequest) -> str:
    """Kill a process by PID."""
```

## Full Decorator Reference

```python
@power(
    name: str,          # Power name (e.g. "get_metrics", "hort")
    *,
    sub: str = "",      # Subcommand (e.g. "info" for /hort info)
    mcp: bool = True,   # Expose as MCP tool for AI
    command: bool = False,  # Expose as slash command in /help
    admin_only: bool = False,  # Restrict to admin users
)
```

Description comes from the docstring. Input/output models
inferred from type hints. Sync handlers auto-wrapped in
`asyncio.to_thread()`.

## Power Naming

Powers are stored with dotted names for subcommands:

| Declaration | Internal name | Command |
|---|---|---|
| `@power("cpu")` | `"cpu"` | `/cpu` |
| `@power("hort")` | `"hort"` | `/hort` |
| `@power("hort", sub="info")` | `"hort.info"` | `/hort info` or `/hort__info` |

Cross-llming calls use the internal name:

```python
await self.llmings["hort-chief"].call("hort.info")
```
