# Llming Architecture v2

The clean separation between what a llming IS (class), what a running llming HAS (instance), and how llmings interact without coupling.

## Class vs Instance

```mermaid
graph TD
    subgraph class ["LlmingClass (installed)"]
        MANIFEST["Manifest"]
        CRED_SPECS["Credential Specs"]
        SOUL_FILE["Soul (SOUL.md)"]
        CODE["Python module"]
    end
    
    subgraph inst1 ["LlmingInstance: work-email"]
        CFG1["Config: tenant=company"]
        CRED1["Credentials: ms_work_oauth"]
        PULSE1["Pulse state"]
    end
    
    subgraph inst2 ["LlmingInstance: personal-email"]
        CFG2["Config: tenant=common"]
        CRED2["Credentials: ms_personal_oauth"]
        PULSE2["Pulse state"]
    end
    
    class --> inst1
    class --> inst2
```

| | LlmingClass | LlmingInstance |
|---|---|---|
| **What** | Installed package | Running service |
| **Lifecycle** | Discovered at startup | Created from YAML config |
| **Count** | One per type | Zero to many per type |
| **Has** | Manifest, code, Soul, credential specs | Config, credentials, pulse, scheduler |
| **Example** | `microsoft/office365` | `work-email`, `personal-email` |

### Singleton vs Multi-Instance

Declared in manifest:

```json
{
  "name": "system-monitor",
  "singleton": true
}
```

```json
{
  "name": "office365",
  "singleton": false
}
```

Singletons: `system-monitor`, `network-monitor`, `clipboard`, `lens`
Multi-instance: `office365`, `ftp-storage`, `database`, `claude-code`

## The Five Parts

Every llming instance has up to five parts. No mixins — each part is a standardized interface on `LlmingBase`.

### Soul

What the llming knows. Loaded from `SOUL.md`, injected into agent prompts.

```python
class LlmingBase:
    @property
    def soul(self) -> str:
        """Return Soul text (auto-loaded from SOUL.md)."""
        return self._soul_text
```

No code needed per-llming. The framework loads `SOUL.md` automatically.

### Powers

What the llming can DO. Three power types, all returned by `get_powers()`:

```python
class PowerType(str, Enum):
    MCP = "mcp"          # MCP tools (JSON-RPC, structured I/O)
    COMMAND = "command"   # Slash commands (/cpu, /horts — text/HTML response)
    ACTION = "action"     # Publishable Python functions (Pydantic in/out)

@dataclass
class Power:
    name: str
    type: PowerType
    description: str
    input_schema: dict | type[BaseModel]   # JSON Schema or Pydantic model
    output_schema: dict | type[BaseModel] | None = None
    handler: Callable | None = None
    admin_only: bool = False
    
class LlmingBase:
    def get_powers(self) -> list[Power]:
        """Declare all powers this llming provides."""
        return []
    
    async def execute_power(self, name: str, arguments: dict) -> Any:
        """Execute a power by name."""
```

#### MCP Powers

Standard MCP tools — JSON in, JSON out. Used by AI agents:

```python
Power(
    name="get_cpu",
    type=PowerType.MCP,
    description="Get current CPU usage",
    input_schema={"type": "object", "properties": {}},
)
```

#### Command Powers

Slash commands — text/HTML response. Used by humans via Telegram/Wire:

```python
Power(
    name="horts",
    type=PowerType.COMMAND,
    description="Show sub-hort topology",
    input_schema={"type": "object", "properties": {
        "args": {"type": "string", "default": ""}
    }},
    admin_only=True,
)
```

#### Action Powers

Publishable Python functions with Pydantic models. Used by other llmings and external callers:

```python
from pydantic import BaseModel

class CpuRequest(BaseModel):
    include_per_core: bool = False

class CpuResponse(BaseModel):
    total_percent: float
    per_core: list[float] = []
    temperature: float | None = None

Power(
    name="get_cpu_status",
    type=PowerType.ACTION,
    description="Get CPU metrics",
    input_schema=CpuRequest,
    output_schema=CpuResponse,
)
```

Actions are auto-exposed as:
- MCP tools (JSON Schema generated from Pydantic)
- REST endpoints (`POST /api/llmings/{instance}/actions/{name}`)
- Inter-llming calls (via the message bus, no direct imports)

### Pulse

What the llming RADIATES. Live state + subscribable events.

```python
class LlmingBase:
    def get_pulse(self) -> dict[str, Any]:
        """Return current live state (static read)."""
        return {}
    
    async def emit_pulse(self, event: str, data: dict) -> None:
        """Push an event to all subscribers."""
        await self._pulse_bus.emit(self.instance_name, event, data)
    
    def get_pulse_channels(self) -> list[str]:
        """Declare subscribable event channels."""
        return []
```

Every llming gets a scheduler by default — no mixin needed:

```python
class LlmingBase:
    @property
    def scheduler(self) -> Scheduler:
        """Built-in job scheduler."""
        return self._scheduler
```

Jobs declared in manifest run automatically:

```json
{
  "jobs": [
    {"id": "poll-metrics", "method": "poll_metrics", "interval_seconds": 5}
  ]
}
```

### Cards

How the llming LOOKS. UI components in `cards.js` (renamed from `panel.js`):

```javascript
// cards.js
class SystemMonitorCards extends LlmingCards {
    static id = 'system-monitor';
    static icon = 'ph ph-cpu';
    
    renderThumbnail(ctx, width, height) { /* grid card */ }
    
    setup(app) {
        app.component('system-monitor-detail', { /* detail panel */ });
        app.component('system-monitor-widget', { /* embeddable widget */ });
    }
}
```

### Envoy

Where the llming executes REMOTELY. Declared in YAML, not in code:

```yaml
llmings:
  claude:
    type: openhort/claude-code
    envoy:
      container:
        image: openhort-claude-code
        memory: 2g
```

## Isolation: No Direct Imports

All llming code lives in `llmings/` (separate package). The main process never imports from it. Each llming runs in its own subprocess.

```python
# FORBIDDEN — direct coupling
from llmings.core.system_monitor.provider import SystemMonitor

# ALLOWED — call powers via handle
result = await self.llmings["system-monitor"].call("get_metrics")

# ALLOWED — subscribe to named channels
@on("cpu_spike")
async def handle_spike(self, data: dict) -> None: ...

# ALLOWED — read shared vault data
data = await self.vaults["system-monitor"].read("latest_metrics")
```

### Inter-Llming Communication

All communication goes through the framework's message bus:

```python
class LlmingBase:
    async def call(self, target: str, power: str, args: dict = {}) -> Any:
        """Call another llming's power. Goes through permission checks."""
    
    async def read_pulse(self, target: str) -> dict:
        """Read another llming's current pulse state."""
    
    def subscribe(self, target: str, event: str, handler: Callable) -> None:
        """Subscribe to another llming's pulse events."""
    
    def unsubscribe(self, target: str, event: str) -> None:
        """Unsubscribe from pulse events."""
```

The message bus enforces:
- Group isolation (taint rules)
- Wire permissions (allow/deny)
- Rate limiting
- Audit logging

A llming calling another llming looks the same whether they're on the same machine, in a container, or on a remote hort — the bus routes through H2H if needed.

## LlmingBase — Complete Interface

```python
class LlmingBase:
    """Base class for all llmings. No mixins."""
    
    # ── Identity ──
    instance_name: str          # "work-email" (from YAML)
    class_name: str             # "office365" (from manifest)
    
    # ── Lifecycle ──
    def activate(self, config: dict) -> None: ...
    def deactivate(self) -> None: ...
    
    # ── Soul (auto-loaded) ──
    @property
    def soul(self) -> str: ...
    
    # ── Powers ──
    def get_powers(self) -> list[Power]: ...
    async def execute_power(self, name: str, args: dict) -> Any: ...
    
    # ── Pulse ──
    def get_pulse(self) -> dict: ...
    def get_pulse_channels(self) -> list[str]: ...
    async def emit_pulse(self, event: str, data: dict) -> None: ...
    
    # ── Cards (framework handles, no method needed) ──
    
    # ── Inter-llming ──
    async def call(self, target: str, power: str, args: dict = {}) -> Any: ...
    async def read_pulse(self, target: str) -> dict: ...
    def subscribe(self, target: str, event: str, handler: Callable) -> None: ...
    
    # ── Built-in services (no mixins) ──
    @property
    def scheduler(self) -> Scheduler: ...
    @property
    def store(self) -> Store: ...
    @property
    def files(self) -> FileStore: ...
    @property
    def credentials(self) -> CredentialAccess: ...
    @property
    def log(self) -> Logger: ...
```

## Example: System Monitor

```python
class SystemMonitor(LlmingBase):
    """CPU, memory, disk monitoring."""
    
    _latest: dict = {}
    
    def activate(self, config: dict) -> None:
        self.log.info("System monitor activated")
    
    # ── Powers ──
    
    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="get_metrics",
                type=PowerType.ACTION,
                description="Get current system metrics",
                input_schema=MetricsRequest,
                output_schema=MetricsResponse,
            ),
            Power(
                name="cpu",
                type=PowerType.COMMAND,
                description="Show CPU usage",
            ),
        ]
    
    async def execute_power(self, name: str, args: dict) -> Any:
        if name == "get_metrics":
            return MetricsResponse(
                cpu=self._latest.get("cpu", 0),
                memory=self._latest.get("mem", 0),
                disk=self._latest.get("disk", 0),
            )
        if name == "cpu":
            return f"CPU: {self._latest.get('cpu', '?')}%"
    
    # ── Pulse ──
    
    def get_pulse(self) -> dict:
        return self._latest
    
    def get_pulse_channels(self) -> list[str]:
        return ["cpu_spike", "memory_warning", "disk_full"]
    
    # ── Scheduled job (declared in manifest, called by framework) ──
    
    async def poll_metrics(self) -> None:
        import psutil
        self._latest = {
            "cpu": psutil.cpu_percent(),
            "mem": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage("/").percent,
        }
        if self._latest["cpu"] > 90:
            await self.emit_pulse("cpu_spike", self._latest)
```

## Example: Status Dashboard (consumes other llmings)

```python
class StatusDashboard(LlmingBase):
    """Aggregates pulse data from multiple llmings."""
    
    def activate(self, config: dict) -> None:
        # Subscribe to events from other llmings (no imports!)
        self.subscribe("system-monitor", "cpu_spike", self._on_spike)
        self.subscribe("network-monitor", "connection_lost", self._on_network)
    
    async def _on_spike(self, data: dict) -> None:
        self.log.warning("CPU spike: %s%%", data.get("cpu"))
    
    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="overview",
                type=PowerType.COMMAND,
                description="System overview",
            ),
        ]
    
    async def execute_power(self, name: str, args: dict) -> Any:
        if name == "overview":
            # Read pulse from other llmings — no direct import
            cpu = await self.read_pulse("system-monitor")
            net = await self.read_pulse("network-monitor")
            disk = await self.read_pulse("disk-usage")
            return (
                f"CPU: {cpu.get('cpu', '?')}%\n"
                f"MEM: {cpu.get('mem', '?')}%\n"
                f"NET: {net.get('upload', '?')} up / {net.get('download', '?')} down\n"
                f"DISK: {disk.get('percent', '?')}%"
            )
```

## YAML: Multiple Instances

```yaml
llmings:
  # Singleton — one instance
  system-monitor:
    type: openhort/system-monitor

  # Singleton — one clipboard
  clipboard:
    type: openhort/clipboard

  # Multi-instance — different accounts
  work-email:
    type: microsoft/office365
    config:
      tenant: company.onmicrosoft.com
    credential: ms_work_oauth

  personal-email:
    type: microsoft/office365
    config:
      tenant: common
    credential: ms_personal_oauth

  # Multi-instance — different servers
  prod-db:
    type: generic/database
    config:
      host: db.prod.internal
    credential: prod_db_creds

  dev-db:
    type: generic/database
    config:
      host: localhost:5432
    credential: dev_db_creds
```

## Migration Path

| Old (v1) | New (v2) |
|---|---|
| `PluginBase` | `LlmingBase` |
| `MCPMixin.get_mcp_tools()` | `get_powers()` with `PowerType.MCP` |
| `ConnectorMixin.get_connector_commands()` | `get_powers()` with `PowerType.COMMAND` |
| `ScheduledMixin` | Built-in `self.scheduler` + manifest `jobs:` |
| `DocumentMixin` | Soul (SOUL.md) or Power (action) |
| `IntentMixin` | Remove (dead code) |
| `get_status()` | `get_pulse()` |
| `static/panel.js` | `static/cards.js` |
| `PluginContext` | Built into `LlmingBase` properties |
| `plugin_id` | `instance_name` + `class_name` |
| Direct imports between plugins | `self.call()` / `self.read_pulse()` / `self.subscribe()` |

## File Structure (After Migration)

```
hort/
  llming/
    base.py           # LlmingBase
    powers.py          # Power, PowerType
    pulse.py           # PulseBus, PulseState
    registry.py        # LlmingRegistry (class + instance management)
    scheduler.py       # Scheduler (built-in, not a mixin)
    store.py           # Store, FileStore (per-instance)
  credentials/
    vault.py           # (already done)
    manager.py         # (already done)
  extensions/core/
    system_monitor/
      manifest.json    # (renamed from extension.json)
      provider.py
      SOUL.md
      static/cards.js
```
