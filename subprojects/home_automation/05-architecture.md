# Plugin Architecture & Integration Strategy

## Core Design: Trait-Based Device Model

Devices are compositions of **traits** (capabilities), not class hierarchies.
This matches Matter's cluster model and scales to any device type.

```
Device: "Kitchen Ceiling Light"
├── Trait: OnOff         → state: bool, commands: on/off/toggle
├── Trait: Brightness    → brightness: 0-255, commands: set_brightness
├── Trait: ColorTemp     → mireds: 153-500, commands: set_color_temp
└── Trait: Reachable     → online: bool, last_seen: datetime
```

```
Device: "Living Room Thermostat"
├── Trait: Climate       → current_temp, target_temp, mode, action
├── Trait: Humidity      → current_humidity: float
├── Trait: Battery       → level: 0-100%
└── Trait: Reachable     → online: bool
```

---

## 1. Trait Definitions

### Core Traits

```python
class OnOff:
    state: bool
    # Commands: turn_on(), turn_off(), toggle()

class Brightness(OnOff):
    brightness: int  # 0-255
    # Commands: set_brightness(value, transition_ms=None)

class ColorTemperature(Brightness):
    color_temp_mireds: int  # 153-500
    min_mireds: int
    max_mireds: int
    # Commands: set_color_temp(mireds, transition_ms=None)

class Color(Brightness):
    hue: float          # 0-360
    saturation: float   # 0-100
    color_mode: Literal["hs", "xy", "rgb", "ct"]
    # Commands: set_color(hue, sat, transition_ms=None)
    #           set_xy(x, y, transition_ms=None)

class EnergyMonitor:
    power_w: float
    voltage_v: float | None
    current_a: float | None
    total_kwh: float | None

class Climate:
    current_temp: float
    target_temp: float
    target_temp_high: float | None  # auto mode
    target_temp_low: float | None   # auto mode
    mode: Literal["off", "heat", "cool", "auto", "fan_only", "dry"]
    action: Literal["idle", "heating", "cooling", "drying", "fan"]
    fan_mode: Literal["auto", "low", "medium", "high"] | None
    # Commands: set_mode(), set_temperature(), set_fan_mode()

class Cover:
    position: int      # 0-100 (0=closed, 100=open, normalized)
    tilt: int | None   # 0-100
    state: Literal["open", "closed", "opening", "closing", "stopped"]
    # Commands: open(), close(), stop(), set_position(), set_tilt()

class Lock:
    state: Literal["locked", "unlocked", "jammed", "locking", "unlocking"]
    door_state: Literal["open", "closed"] | None
    battery: int | None
    # Commands: lock(), unlock()

class MediaPlayer:
    state: Literal["off", "idle", "playing", "paused", "buffering"]
    volume: int          # 0-100
    muted: bool
    media_title: str | None
    media_artist: str | None
    source: str | None
    source_list: list[str] | None
    # Commands: play(), pause(), stop(), next(), previous(),
    #           set_volume(), mute(), select_source()

class Vacuum:
    state: Literal["docked", "cleaning", "returning", "paused", "error", "idle"]
    battery: int
    fan_speed: Literal["quiet", "standard", "turbo", "max"] | None
    # Commands: start(), stop(), pause(), return_to_dock(), locate()

class Camera:
    stream_url: str    # RTSP or other
    snapshot_url: str | None
    ptz_capable: bool
    # Commands: snapshot() -> bytes, ptz_move(direction, speed),
    #           ptz_preset(name)

class Sensor:
    value: float | bool | str
    unit: str
    device_class: str  # temperature, humidity, motion, door, etc.
    last_updated: datetime

class Battery:
    level: int         # 0-100%
    charging: bool | None

class Reachable:
    online: bool
    last_seen: datetime
```

### State Machines

Key device types have defined state machines:

```
Lock:
  locked ←→ unlocking → unlocked ←→ locking → locked
  (jammed reachable from locking/unlocking)

Cover:
  closed → opening → open → closing → closed
  (stopped reachable from opening/closing)

Vacuum:
  docked → cleaning → returning → docked
  (paused reachable from cleaning, error from any)

Washing Machine:
  idle → [delay_start →] running(wash→rinse→spin→[dry→]) → finished → idle
  (paused reachable from running, error from any running sub-state)
```

---

## 2. Adapter Plugin Architecture

### Overview

```
┌─────────────────────────────────────────────────────┐
│                  openhort core                       │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Device   │  │ Event    │  │ State Store      │  │
│  │ Registry │  │ Bus      │  │ (in-memory+disk) │  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────────┘  │
│       │              │               │              │
│  ┌────┴──────────────┴───────────────┴──────────┐   │
│  │              Adapter Interface                │   │
│  │  discover() · setup() · command() · shutdown()│   │
│  └──────┬──────────┬──────────┬─────────────────┘   │
└─────────┼──────────┼──────────┼─────────────────────┘
          │          │          │
    ┌─────┴───┐ ┌────┴────┐ ┌──┴──────┐
    │  MQTT   │ │ HA WS   │ │ Shelly  │  ...
    │ Adapter │ │ Adapter │ │ Adapter │
    └─────────┘ └─────────┘ └─────────┘
```

### Adapter Base Class

```python
from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass

@dataclass
class DeviceInfo:
    """Discovered device."""
    id: str                     # unique identifier
    name: str                   # human-readable name
    manufacturer: str
    model: str
    traits: list[str]           # ["onoff", "brightness", "color_temp"]
    via_device: str | None      # bridge/hub ID if bridged

class AdapterBase(ABC):
    """Base class for all device adapters."""

    @abstractmethod
    async def setup(self, config: dict) -> None:
        """Initialize adapter with user configuration."""

    @abstractmethod
    async def discover(self) -> list[DeviceInfo]:
        """Discover devices on the network."""

    @abstractmethod
    async def command(self, device_id: str, trait: str,
                      command: str, params: dict) -> None:
        """Send a command to a device.

        Example: command("light_1", "brightness", "set_brightness",
                        {"value": 200, "transition_ms": 500})
        """

    @abstractmethod
    async def get_state(self, device_id: str) -> dict[str, Any]:
        """Get current state of all traits for a device."""

    async def subscribe(self, device_id: str,
                        callback: Callable) -> None:
        """Subscribe to state changes (optional, adapters can push)."""

    async def shutdown(self) -> None:
        """Clean up resources."""

    # --- Lifecycle hooks ---
    async def on_device_added(self, device_id: str) -> None:
        """Called when user confirms discovered device."""

    async def on_device_removed(self, device_id: str) -> None:
        """Called when user removes a device."""
```

### Example: MQTT Adapter

```python
class MQTTAdapter(AdapterBase):
    """Adapter for MQTT-based devices (Zigbee2MQTT, Tasmota, Shelly MQTT)."""

    async def setup(self, config: dict) -> None:
        self.client = aiomqtt.Client(
            hostname=config["broker"],
            port=config.get("port", 1883),
            username=config.get("username"),
            password=config.get("password"),
        )
        await self.client.connect()
        # Subscribe to discovery topics
        await self.client.subscribe("homeassistant/#")   # HA MQTT discovery
        await self.client.subscribe("zigbee2mqtt/#")     # Z2M devices
        await self.client.subscribe("tasmota/#")         # Tasmota devices

    async def discover(self) -> list[DeviceInfo]:
        # Parse MQTT discovery messages into DeviceInfo
        ...

    async def command(self, device_id: str, trait: str,
                      command: str, params: dict) -> None:
        # Translate trait command → MQTT topic + payload
        topic = self._device_command_topic(device_id)
        payload = self._translate_command(device_id, trait, command, params)
        await self.client.publish(topic, payload)

    async def get_state(self, device_id: str) -> dict:
        # Return cached state from MQTT retained messages
        return self._state_cache[device_id]
```

### Example: Home Assistant Adapter

```python
class HomeAssistantAdapter(AdapterBase):
    """Adapter that bridges to a Home Assistant instance."""

    async def setup(self, config: dict) -> None:
        self.ws = await websockets.connect(
            f"ws://{config['host']}:8123/api/websocket"
        )
        # Authenticate
        await self.ws.recv()  # auth_required
        await self.ws.send(json.dumps({
            "type": "auth",
            "access_token": config["token"]
        }))
        await self.ws.recv()  # auth_ok

        # Subscribe to state changes
        await self.ws.send(json.dumps({
            "id": 1,
            "type": "subscribe_events",
            "event_type": "state_changed"
        }))

    async def discover(self) -> list[DeviceInfo]:
        # Get all HA entities, map to DeviceInfo + traits
        await self.ws.send(json.dumps({"id": 2, "type": "get_states"}))
        result = await self.ws.recv()
        return self._map_entities_to_devices(result)

    async def command(self, device_id: str, trait: str,
                      command: str, params: dict) -> None:
        # Map trait command → HA service call
        domain, service, data = self._map_command(device_id, trait, command, params)
        await self.ws.send(json.dumps({
            "id": self._next_id(),
            "type": "call_service",
            "domain": domain,
            "service": service,
            "service_data": data
        }))

    def _map_command(self, device_id, trait, command, params):
        """Translate unified command to HA service call."""
        entity_id = self._device_to_entity[device_id]
        domain = entity_id.split(".")[0]

        if trait == "onoff" and command == "turn_on":
            return domain, "turn_on", {"entity_id": entity_id}
        elif trait == "brightness" and command == "set_brightness":
            return domain, "turn_on", {
                "entity_id": entity_id,
                "brightness": params["value"]
            }
        elif trait == "climate" and command == "set_temperature":
            return "climate", "set_temperature", {
                "entity_id": entity_id,
                "temperature": params["target"]
            }
        # ... etc
```

---

## 3. Event Bus

All state changes flow through a central async event bus:

```python
class EventBus:
    """Central event bus for device state changes."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable) -> Callable:
        """Subscribe to events. Returns unsubscribe function."""
        self._subscribers[event_type].append(callback)
        return lambda: self._subscribers[event_type].remove(callback)

    async def emit(self, event_type: str, data: dict) -> None:
        """Emit an event to all subscribers."""
        for callback in self._subscribers.get(event_type, []):
            try:
                await callback(data)
            except Exception:
                logger.exception(f"Error in event handler for {event_type}")

    # Convenience methods
    async def state_changed(self, device_id: str, trait: str,
                           old_state: Any, new_state: Any) -> None:
        await self.emit("state_changed", {
            "device_id": device_id,
            "trait": trait,
            "old": old_state,
            "new": new_state,
            "timestamp": datetime.utcnow(),
        })
```

**Event types:**
- `state_changed` — device trait value changed
- `device_discovered` — new device found by adapter
- `device_online` / `device_offline` — reachability
- `adapter_started` / `adapter_stopped` — adapter lifecycle
- `command_sent` / `command_failed` — command tracking

---

## 4. State Store

```python
class StateStore:
    """In-memory state with persistence."""

    def __init__(self, persist_path: Path):
        self._state: dict[str, dict[str, Any]] = {}  # device_id → trait → value
        self._persist_path = persist_path

    def get(self, device_id: str, trait: str = None) -> Any:
        if trait:
            return self._state.get(device_id, {}).get(trait)
        return self._state.get(device_id, {})

    def set(self, device_id: str, trait: str, value: Any) -> None:
        self._state.setdefault(device_id, {})[trait] = value

    async def persist(self) -> None:
        """Write to disk (atomic via temp file + rename)."""
        ...

    async def load(self) -> None:
        """Load from disk."""
        ...
```

**Persistence strategy:**
- State cache is in-memory for speed
- Periodic flush to disk (every 30s) via atomic temp+rename
- On startup, load from disk then reconcile with adapter discovery
- History/time-series in separate SQLite store for charts/analytics

---

## 5. Plugin Isolation Model

### Recommended Hybrid

| Plugin Type | Isolation | Communication | Use Case |
|-------------|-----------|---------------|----------|
| Built-in adapters | In-process (asyncio) | Direct method calls | MQTT, HA, Shelly |
| Community adapters | Separate process | JSON-RPC over Unix socket | Third-party integrations |
| Hardware adapters | Docker container | JSON-RPC over TCP | Zigbee/Z-Wave USB sticks |

### In-Process (Built-in Adapters)

```python
# Loaded as part of openhort core
class PluginManager:
    async def load_adapter(self, name: str, config: dict):
        module = importlib.import_module(f"hort.home.adapters.{name}")
        adapter = module.Adapter()
        await adapter.setup(config)
        self._adapters[name] = adapter
        # Start listening for state changes
        asyncio.create_task(adapter.run(self._event_bus))
```

### Separate Process (Community Adapters)

```
openhort process ←→ Unix socket (JSON-RPC) ←→ plugin process
```

Protocol:
```json
// openhort → plugin: discover devices
{"jsonrpc": "2.0", "method": "discover", "id": 1}

// plugin → openhort: state update
{"jsonrpc": "2.0", "method": "state_changed",
 "params": {"device_id": "light_1", "trait": "onoff", "value": true}}

// openhort → plugin: send command
{"jsonrpc": "2.0", "method": "command", "id": 2,
 "params": {"device_id": "light_1", "trait": "brightness",
            "command": "set_brightness", "params": {"value": 200}}}
```

Resource limits:
```python
import resource

def apply_limits():
    # Memory: 256 MB
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    # CPU time: checked by watchdog
    # File descriptors: 128
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
```

### Container (Hardware Adapters)

```yaml
# docker-compose for Zigbee adapter
services:
  zigbee-adapter:
    image: openhort/adapter-zigbee:latest
    devices:
      - /dev/ttyUSB0:/dev/ttyUSB0   # USB Zigbee coordinator
    environment:
      - OPENHORT_HOST=host.docker.internal
      - OPENHORT_PORT=8940
    mem_limit: 512m
    cpus: 1.0
    restart: unless-stopped
```

### Permission Model

Each adapter declares required permissions in its manifest:

```yaml
# adapter-manifest.yml
name: tuya-local
version: 1.0.0
author: community
description: "Local Tuya device control via tinytuya"

permissions:
  network:
    - "192.168.0.0/16"      # LAN access for device discovery
    - "openapi.tuyaus.com"  # Cloud API for initial key extraction
  device_types:
    - light
    - switch
    - sensor
  storage_mb: 50             # Persistent storage quota
  memory_mb: 256             # Max RAM
```

### Crash Recovery

1. Log crash with full traceback
2. Mark all adapter entities as "unavailable"
3. Exponential backoff restart (5s, 10s, 20s, 40s, max 5min)
4. After 5 consecutive crashes → disable adapter, notify user
5. User can manually re-enable from UI

### Hot-Reload

1. User triggers reload (API call or file change detection)
2. Core sends "shutdown" signal → adapter has 5s to persist state and close connections
3. Core kills adapter if still running after 5s
4. Core marks all adapter entities as "unavailable"
5. For in-process: `plugin.shutdown()` → remove ref → `importlib.reload(module)` → create new instance → `plugin.setup(config)`
6. For process/container: kill → restart
7. Adapter re-discovers devices, entities transition to "available"

---

## 6. UI Integration with openhort

### Device Panel in the SPA

Home automation devices appear as a panel in the openhort Vue/Quasar SPA:

```
┌────────────────────────────────────────┐
│  🏠 Home         [Rooms ▼] [Search]   │
├────────────────────────────────────────┤
│  Living Room                           │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │
│  │ ☀️   │ │ 🌡️   │ │ 📺   │ │ 💡   │  │
│  │Ceiling│ │Thermo│ │ TV   │ │Lamp  │  │
│  │ 80%  │ │22.5°C│ │ On   │ │ Off  │  │
│  └──────┘ └──────┘ └──────┘ └──────┘  │
│                                        │
│  Kitchen                               │
│  ┌──────┐ ┌──────┐ ┌──────┐           │
│  │ 💡   │ │ 🔌   │ │ 🧹   │           │
│  │Light │ │Coffee│ │Vacuum│           │
│  │ On   │ │ 45W  │ │Docked│           │
│  └──────┘ └──────┘ └──────┘           │
│                                        │
│  Security                              │
│  ┌──────┐ ┌──────┐ ┌──────┐           │
│  │ 🔒   │ │ 📷   │ │ 🚪   │           │
│  │Front │ │Camera│ │Garage│           │
│  │Locked│ │Motion│ │Closed│           │
│  └──────┘ └──────┘ └──────┘           │
└────────────────────────────────────────┘
```

**Interaction model:**
- Tap device card → quick action (toggle light, lock/unlock)
- Long press → detail panel (brightness slider, color picker, thermostat controls)
- Swipe between rooms
- Camera cards show live thumbnail (existing openhort thumbnail system)

### Control WebSocket Messages

Extend the existing openhort control WebSocket with home automation messages:

```json
// Client → Server: command
{"type": "home.command", "device_id": "light_1",
 "trait": "brightness", "command": "set_brightness",
 "params": {"value": 200}}

// Server → Client: state update
{"type": "home.state", "device_id": "light_1",
 "state": {"onoff": {"state": true},
            "brightness": {"brightness": 200},
            "reachable": {"online": true}}}

// Client → Server: get all devices
{"type": "home.devices"}

// Server → Client: device list
{"type": "home.devices.result", "devices": [
  {"id": "light_1", "name": "Kitchen Light", "room": "Kitchen",
   "traits": ["onoff", "brightness", "color_temp"],
   "state": {"onoff": {"state": true}, "brightness": {"brightness": 200}}}
]}
```

---

## 7. Scene & Automation Layer

### Scenes

```python
@dataclass
class Scene:
    id: str
    name: str
    icon: str
    targets: list[SceneTarget]  # device_id + trait + value

@dataclass
class SceneTarget:
    device_id: str
    trait: str
    value: Any
    transition_ms: int | None = None

# Example: "Movie Night"
Scene(
    id="movie_night",
    name="Movie Night",
    icon="theaters",
    targets=[
        SceneTarget("light_living", "brightness", 25, transition_ms=2000),
        SceneTarget("light_living", "color_temp", 450),  # warm
        SceneTarget("cover_living", "position", 0),       # blinds closed
        SceneTarget("tv_living", "onoff", True),
    ]
)
```

### Automations

```python
@dataclass
class Automation:
    id: str
    name: str
    enabled: bool
    trigger: Trigger
    conditions: list[Condition]
    actions: list[Action]

# Trigger types
StateTrigger(device_id="sensor_motion", trait="sensor", from_val=False, to_val=True)
TimeTrigger(at="sunset", offset_minutes=-30)
ScheduleTrigger(cron="0 7 * * 1-5")  # weekdays at 7am

# Condition types
StateCondition(device_id="input_mode", trait="sensor", value="home")
TimeCondition(after="18:00", before="06:00")

# Action types
CommandAction(device_id="light_1", trait="onoff", command="turn_on", params={})
SceneAction(scene_id="movie_night")
DelayAction(seconds=5)
NotifyAction(message="Motion detected in {device_name}")
```

---

## 8. Integration with Existing openhort

### How it fits

The home automation system integrates as an **extension** in the existing openhort
extension system:

```
hort/extensions/home/
├── __init__.py
├── manifest.json           # Extension manifest
├── adapters/
│   ├── mqtt.py             # MQTT adapter
│   ├── homeassistant.py    # HA WebSocket adapter
│   ├── shelly.py           # Shelly direct adapter
│   ├── tuya.py             # Tuya local adapter
│   └── matter.py           # Matter adapter
├── models.py               # Trait definitions, device models
├── registry.py             # Device registry
├── events.py               # Event bus
├── state.py                # State store
├── scenes.py               # Scene engine
├── automations.py          # Automation engine
└── static/
    └── panel.js            # Vue component for home panel
```

### Leveraging existing openhort infrastructure

| openhort Feature | Home Automation Use |
|-----------------|---------------------|
| Control WebSocket | Home automation commands + state updates |
| Thumbnail system | Camera snapshots in device grid |
| Stream system | Live camera streams |
| Signal system | Automation triggers + actions |
| Extension system | Adapter plugins |
| Container system | Isolated hardware adapters |
| Remote access | Control home devices from anywhere |
| Telegram connector | "Turn off the lights" via Telegram |

### What openhort adds as an overlay

1. **Remote access** — control home devices from anywhere via P2P or cloud proxy
2. **Mobile-first UI** — responsive Quasar interface optimized for phone control
3. **AI integration** — natural language device control via LLM extensions
4. **Screen + home in one** — monitor your computer screens AND your home from one app
5. **Telegram bot** — conversational device control
6. **Multi-machine** — control devices across multiple homes/locations via targets

---

## 9. Implementation Roadmap (Suggested)

### Phase 1: Foundation
- Trait model + device registry + state store
- Event bus
- Control WebSocket messages for home automation
- Basic UI panel (device grid with tap-to-toggle)

### Phase 2: Core Adapters
- MQTT adapter (covers Zigbee2MQTT, Tasmota, ESPHome, Shelly MQTT)
- Home Assistant WebSocket adapter
- Device detail panels (light color picker, thermostat, camera)

### Phase 3: Direct Adapters
- Shelly native adapter (REST + WebSocket, no hub needed)
- Tuya local adapter (tinytuya)
- ONVIF camera adapter (with go2rtc integration)

### Phase 4: Advanced
- Matter adapter (python-matter-server)
- Scene engine
- Automation engine
- Telegram commands for devices
- AI-powered natural language control

### Phase 5: Ecosystem
- Community adapter API (process isolation, JSON-RPC)
- Adapter marketplace / discovery
- Container-based hardware adapters (Zigbee, Z-Wave)
