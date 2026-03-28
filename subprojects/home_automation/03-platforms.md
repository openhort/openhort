# Integration Platforms — Home Assistant, OpenHAB, and Others

## Strategy: Don't Reimplement — Bridge

There are 2,000+ device integrations in Home Assistant alone. Reimplementing even 1% would
take years. The correct strategy: **use existing platforms as protocol bridges** and build
openhort's value on top (remote access, mobile UI, automation overlay, AI control).

```
┌──────────────────────────────────────┐
│          openhort overlay             │
│  (mobile UI, remote access, AI)      │
├──────────┬──────────┬────────────────┤
│ MQTT     │ HA WS    │ Direct         │
│ adapter  │ adapter  │ adapters       │
├──────────┼──────────┼────────────────┤
│ Mosquitto│ Home     │ Shelly, Tuya,  │
│ broker   │Assistant │ python-matter  │
└──────────┴──────────┴────────────────┘
     ↕           ↕            ↕
  Zigbee2MQTT  2000+      Individual
  Tasmota     integrations  devices
  ESPHome
```

---

## 1. Home Assistant — Primary Bridge Target

### Architecture

**Home Assistant Core** — pure Python (3.12+) application:
- Automation engine, state machine, event bus, web UI
- 2,000+ integrations (protocol adapters)
- Installable via pip/venv on any Linux/macOS

**Home Assistant Supervisor** — Docker orchestration:
- Manages Core container + add-on containers (MQTT broker, Node-RED, etc.)
- REST API on internal port 80 (`http://supervisor/`)

**Home Assistant OS (HAOS)** — minimal Linux (Buildroot):
- Runs Supervisor + Core on bare metal or VM
- OTA updates, filesystem management

### Entity Model

Every physical device registers one or more **entities**:

```python
# Each entity has:
entity_id: str     # "light.kitchen_ceiling"
state: str         # "on", "off", "23.5", "locked"
attributes: dict   # {"brightness": 200, "color_temp": 350, "friendly_name": "Kitchen"}
last_changed: dt   # when state last changed
last_updated: dt   # when attributes last updated
```

**Entity domains:** `light`, `switch`, `sensor`, `binary_sensor`, `climate`, `cover`,
`lock`, `media_player`, `camera`, `vacuum`, `fan`, `humidifier`, `water_heater`,
`alarm_control_panel`, `number`, `select`, `button`, `text`, `date`, `time`

**Feature flags** (per domain):
```python
# light features (bitmask)
SUPPORT_BRIGHTNESS = 1
SUPPORT_COLOR_TEMP = 2
SUPPORT_EFFECT = 4
SUPPORT_FLASH = 8
SUPPORT_COLOR = 16
SUPPORT_TRANSITION = 32
```

**Services** (commands) are typed per domain:
```python
# Call a service
light.turn_on(entity_id="light.kitchen", brightness=200, color_temp=350)
climate.set_temperature(entity_id="climate.living_room", temperature=21)
lock.lock(entity_id="lock.front_door")
cover.set_cover_position(entity_id="cover.blinds", position=50)
```

---

### Home Assistant REST API

**Base URL:** `http://<ha-ip>:8123/api/`
**Auth:** `Authorization: Bearer <long_lived_access_token>`

```
GET  /api/                          → API running check
GET  /api/config                    → HA configuration
GET  /api/states                    → All entity states
GET  /api/states/<entity_id>        → Single entity state
POST /api/states/<entity_id>        → Set entity state (for input_* helpers)
POST /api/services/<domain>/<service> → Call a service
POST /api/events/<event_type>       → Fire an event
GET  /api/history/period/<timestamp> → State history
GET  /api/logbook/<timestamp>       → Logbook entries
POST /api/template                  → Render Jinja2 template
```

**Example — turn on a light:**
```bash
curl -X POST http://ha:8123/api/services/light/turn_on \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "light.kitchen", "brightness": 200}'
```

---

### Home Assistant WebSocket API (Primary Integration Path)

**URL:** `ws://<ha-ip>:8123/api/websocket`

This is the **recommended way** to integrate with HA — real-time, bidirectional,
supports subscriptions.

#### Authentication Flow
```json
// 1. Server sends auth_required
{"type": "auth_required", "ha_version": "2024.1.0"}

// 2. Client sends token
{"type": "auth", "access_token": "LONG_LIVED_TOKEN"}

// 3. Server confirms
{"type": "auth_ok", "ha_version": "2024.1.0"}
```

#### Get All States
```json
// Request
{"id": 1, "type": "get_states"}

// Response
{"id": 1, "type": "result", "success": true, "result": [
  {"entity_id": "light.kitchen", "state": "on", "attributes": {"brightness": 200}, ...},
  ...
]}
```

#### Subscribe to State Changes
```json
// Request
{"id": 2, "type": "subscribe_events", "event_type": "state_changed"}

// Events (continuous)
{"id": 2, "type": "event", "event": {
  "event_type": "state_changed",
  "data": {
    "entity_id": "light.kitchen",
    "old_state": {"state": "off", ...},
    "new_state": {"state": "on", "attributes": {"brightness": 200}, ...}
  }
}}
```

#### Call a Service
```json
{"id": 3, "type": "call_service", "domain": "light", "service": "turn_on",
 "service_data": {"entity_id": "light.kitchen", "brightness": 200}}
```

#### Other Commands
```json
// Subscribe to specific entity
{"id": 4, "type": "subscribe_trigger", "trigger": {
  "platform": "state", "entity_id": "binary_sensor.motion"
}}

// Get config
{"id": 5, "type": "get_config"}

// Get services list
{"id": 6, "type": "get_services"}

// Get panels
{"id": 7, "type": "get_panels"}

// Camera snapshot
{"id": 8, "type": "camera_thumbnail", "entity_id": "camera.front_door"}

// Media player thumbnail
{"id": 9, "type": "media_player_thumbnail", "entity_id": "media_player.living_room"}
```

---

### MQTT Discovery (Auto-configuration)

HA automatically creates entities from MQTT messages following a convention:

**Topic pattern:** `homeassistant/<domain>/<object_id>/config`

```json
// Publish to: homeassistant/light/kitchen_light/config
{
  "name": "Kitchen Light",
  "unique_id": "kitchen_light_001",
  "command_topic": "home/kitchen/light/set",
  "state_topic": "home/kitchen/light/state",
  "brightness_command_topic": "home/kitchen/light/brightness/set",
  "brightness_state_topic": "home/kitchen/light/brightness",
  "schema": "json",
  "device": {
    "identifiers": ["kitchen_light_001"],
    "name": "Kitchen Light",
    "model": "Smart Bulb v2",
    "manufacturer": "Acme"
  }
}
```

This is how Zigbee2MQTT, Tasmota, and ESPHome auto-register devices with HA.
It's also how **openhort could register its own virtual devices** with HA.

---

## 2. Other Platforms

### OpenHAB

Java-based, similar concept to Home Assistant.

**Architecture:** Things → Channels → Items
- **Thing:** Physical device with ThingHandler
- **Channel:** Single capability (brightness, temperature)
- **Item:** User-facing state linked to channel (SwitchItem, DimmerItem, ColorItem, NumberItem)

**REST API:** `http://<oh-ip>:8080/rest/`
- `GET /rest/items` → all items
- `POST /rest/items/<name>` → send command
- SSE endpoint: `GET /rest/events` (Server-Sent Events for state changes)

**Pros:** Rule engine (DSL + Blockly + JS/Python), explicit Thing/Channel/Item separation.
**Cons:** Java overhead, smaller community than HA, slower development pace.

### Node-RED

Flow-based automation tool. Not a device platform — an automation overlay.

**Integration:** Runs as HA add-on or standalone. Connects to HA via WebSocket nodes.
Connects to MQTT, HTTP, TCP, WebSocket, and hundreds of node packages.

**Relevance for openhort:** Similar concept — openhort could be an overlay like Node-RED
but focused on remote monitoring/control rather than flow-based automation.

### Hubitat

Closed-source hub with local processing. Z-Wave + Zigbee + WiFi + LAN.
Maker API exposes REST + WebSocket for third-party integration.
**Not a bridge target** — use HA or MQTT instead.

### HomeBridge

Node.js HomeKit bridge. Creates virtual HomeKit accessories for non-HomeKit devices.
2,000+ plugins. **Relevant if Apple HomeKit is the target ecosystem.**
With Matter adoption, HomeBridge is becoming less critical.

---

## 3. Python Libraries for Direct Protocol Access

### Radio/Mesh Protocols
| Library | Protocol | Notes |
|---------|----------|-------|
| `zigpy` | Zigbee | Async, used by HA ZHA integration, supports multiple radios |
| `zwave-js-server-python` | Z-Wave | Client for Z-Wave JS server (Node.js process with USB stick) |
| `python-matter-server` | Matter | Wraps CHIP SDK, WebSocket API, commissioning + control |
| `bleak` | BLE | Cross-platform async BLE, GATT operations |

### WiFi Device Libraries
| Library | Ecosystem | Notes |
|---------|-----------|-------|
| `tinytuya` | Tuya/Smart Life | Local encrypted UDP, protocol 3.1-3.5, needs cloud for keys |
| `python-kasa` | TP-Link Kasa/Tapo | Local TCP, async, both old (XOR) and new (HTTPS) protocols |
| `aioshelly` | Shelly | Gen 1 + Gen 2, REST + CoAP + WebSocket, discovery |
| `aioesphome` | ESPHome | Native API (protobuf over TCP), encrypted, bidirectional |
| `aiohue` | Philips Hue | CLIP v2 API (HTTPS + SSE), async |
| `dirigera` | IKEA DIRIGERA | REST + OAuth2 PKCE |
| `python-miio` | Xiaomi miio | AES-128-CBC encrypted UDP, vacuums/purifiers/fans |
| `meross-iot` | Meross | MQTT-based, local + cloud, async |
| `python-kasa` | TP-Link | Local encrypted, async, Kasa + Tapo families |
| `govee-api-lagging` | Govee | Cloud REST API |

### Camera Libraries
| Library | Protocol | Notes |
|---------|----------|-------|
| `onvif-zeep` | ONVIF | SOAP client, discovery, PTZ, streaming URIs |
| go2rtc | Universal | Not Python — Go binary, but best camera proxy (RTSP→WebRTC) |

### Infrastructure Libraries
| Library | Protocol | Notes |
|---------|----------|-------|
| `aiomqtt` | MQTT | Modern async MQTT client |
| `paho-mqtt` | MQTT | Mature, callback-based |
| `aiocoap` | CoAP | Async CoAP client/server |
| `xknx` | KNX | KNXnet/IP tunneling, async |
| `pymodbus` | Modbus | RTU + TCP, async, widely used for solar/energy |

### Cloud API Libraries
| Library | Service | Notes |
|---------|---------|-------|
| `ring-doorbell` | Ring | Reverse-engineered, fragile |
| `python-ecobee-api` | Ecobee | Official-ish, OAuth2 |
| `python-nest` (SDM) | Google Nest | Device Access API, OAuth2 + Pub/Sub |
| `pylutron-caseta` | Lutron Caseta | LEAP protocol over TLS, local |

---

## 4. Integration Architecture for openhort

### Option A: Home Assistant as sole bridge

```
openhort ←→ HA WebSocket API ←→ All 2000+ HA integrations
```

**Pros:** Immediate access to everything, minimal code.
**Cons:** Requires HA installation, adds dependency, HA becomes single point of failure.

### Option B: MQTT as universal bus

```
openhort ←→ MQTT broker ←→ Zigbee2MQTT, Tasmota, Shelly, ESPHome
                         ←→ HA MQTT integration (bidirectional)
                         ←→ Direct MQTT devices
```

**Pros:** Decoupled, resilient, standard protocol, works without HA.
**Cons:** Not all devices speak MQTT. Cloud-dependent devices need adapters.

### Option C: Hybrid (recommended)

```
openhort
├── MQTT adapter          → Local devices (Zigbee2MQTT, Tasmota, Shelly, ESPHome)
├── HA WebSocket adapter  → Everything else (2000+ integrations, cloud devices)
├── Matter adapter        → New Matter devices (python-matter-server)
├── Direct adapters       → Selected ecosystems (Hue, Tuya, Kasa) for no-HA users
└── ONVIF/RTSP adapter    → Cameras (go2rtc as proxy)
```

**Why hybrid:** Users with HA get instant access to everything. Users without HA still
get coverage for the most popular device ecosystems via direct adapters. MQTT is the
lingua franca — when in doubt, MQTT.
