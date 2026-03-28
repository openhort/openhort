# Device Categories, Capabilities, and Ecosystems

## Device Capability Tiers

Every device has a **type** (light, lock, climate, etc.) and implements one or more
**traits** (capabilities). This is the foundation of the abstraction model.

---

## 1. Lighting

The most mature smart home category. Capabilities form a hierarchy:

| Tier | Capability | Details |
|------|-----------|---------|
| 1 | On/Off | Binary state, reachability |
| 2 | Dimmable | Brightness 0-100% (0-254 Zigbee), transition time |
| 3 | Color Temperature | Mireds 153-500 (≈6500K-2000K), warm/cool |
| 4 | Full Color | RGB, HSV, CIE XY; gamut constraints per bulb |
| 5 | Effects | Candle, color loop, sunrise, music sync |

**Scenes:** Stored groups of light states. Hue stores on bridge (up to 200).

**Real-world gotchas:**
- Color spaces differ: Hue=CIE XY, Zigbee=HSV, Matter=HSV, Tuya=HSV (0-360/0-1000/0-1000). Must convert.
- "Color temp" and "RGB" are often separate modes — can't set both. Need `color_mode` enum.
- Group commands: individual commands to 20 bulbs → visible "popcorn" effect. Use bridge group commands.
- Transition times: Hue supports 0-65534 (100ms units), most WiFi bulbs ignore transitions entirely.

**Ecosystems:**
- **Philips Hue** — Zigbee + bridge, CIE XY color, local REST API (CLIP v2), Entertainment API (UDP low-latency), aiohue
- **IKEA DIRIGERA** — Zigbee 3.0 + bridge, local REST + OAuth2 PKCE, 50-70% cheaper than Hue
- **Tuya/Smart Life** — WiFi, encrypted UDP (tinytuya), data points vary per device
- **Govee** — WiFi + BLE, LAN API (limited), cloud API (full), LED strips/bars
- **WLED** — ESP32 firmware, REST + MQTT + WebSocket + sACN/Art-Net, fully local, open source
- **ESPHome/Tasmota** — Custom firmware, MQTT, fully local

---

## 2. Smart Plugs / Switches

| Capability | Details |
|-----------|---------|
| On/Off | Relay state |
| Energy monitoring | W, V, A, kWh (accuracy varies: Shelly ±1%, cheap Tuya ±10%) |
| Scheduling | On/off timers, countdown, recurring |
| Overload protection | Auto-off at configurable wattage |
| LED indicator | On/off/follow-relay/night-mode |
| Child lock | Physical button disable |
| Power-on behavior | Restore last / always on / always off |

**Ecosystems:** Shelly (best local), TP-Link Kasa, Tuya, Meross, Sonoff/Tasmota

---

## 3. Cameras

| Capability | Protocol |
|-----------|----------|
| Video stream | RTSP (H.264/H.265), HLS, WebRTC (newer) |
| Snapshot | HTTP GET, ONVIF |
| PTZ | ONVIF (continuous/relative/absolute move, presets) |
| Motion detection | On-camera + event callback (ONVIF events, webhooks) |
| Two-way audio | G.711 typically |
| Night vision | IR LEDs, spotlight |
| Privacy mode | Lens cover, stream disable |

**RTSP URL chaos:** Not standardized per manufacturer.
- Reolink: `rtsp://ip/h264Preview_01_main`
- Dahua: `rtsp://ip/cam/realmonitor?channel=1&subtype=0`
- Hikvision: `rtsp://ip/Streaming/Channels/101`

**Best approach:** Use **go2rtc** as universal proxy. It handles RTSP/ONVIF/HomeKit input
and outputs WebRTC/HLS/MJPEG. Already integrates with HA.

**Cloud-only cameras:** Ring, Blink, Nest — hostile to third-party. Use ring-mqtt or accept cloud dependency.

**Matter 1.4 cameras:** WebRTC signaling via Matter, media peer-to-peer. Still very new.

---

## 4. Climate / HVAC

| Capability | Details |
|-----------|---------|
| Temperature | Current reading + target setpoint (single or heat+cool pair) |
| Mode | off, heat, cool, auto, fan_only, dry |
| Fan speed | auto, low, medium, high (or numeric 1-5) |
| Humidity | Current + target (humidifiers/dehumidifiers) |
| Presets | home, away, sleep, eco, boost |
| Schedule | Time-based setpoints |
| Action | What it's actually doing: idle, heating, cooling, drying, fan |

**Complexity:** "System mode" (what it can do) vs "running mode" (what it's doing now) are different.

**Mini-split ACs** via IR blasters (Broadlink, Sensibo, Tado) are **stateless** — send IR codes,
hope for the best, no feedback on actual state.

**Ecosystems:**
- **Ecobee** — Cloud REST API, OAuth2, comfort settings, room sensors
- **Google Nest** — SDM API, $5 fee, OAuth2+Pub/Sub, limited vs old WWN
- **Tado** — Cloud API, local mode experimental
- **Sensibo** — Cloud API for mini-split AC control via IR

---

## 5. Washing Machines / Dryers / Dishwashers

| Capability | Details |
|-----------|---------|
| Status | idle, running, paused, finished, error |
| Current cycle | wash, rinse, spin, dry |
| Program | cotton, synthetics, delicates, eco, quick |
| Time remaining | Estimated |
| Remote start | Requires physical enable for safety |
| Notifications | Cycle complete, error, door open |
| Consumption | Energy/water per cycle |

**Safety:** Most machines require "remote start" enabled via physical button before each cycle.
You can monitor, but starting requires human at the machine.

**Ecosystems:**
- **Bosch/Siemens/Neff/Gaggenau** — Home Connect API (best documented)
- **LG ThinQ** — Reverse-engineered (wideq library)
- **Samsung SmartThings** — Cloud API
- **Miele@home** — Cloud API

**State machine complexity:** 10+ states with program-dependent transitions.

---

## 6. Robot Vacuums

| Capability | Details |
|-----------|---------|
| Commands | start, stop, pause, return to dock, locate |
| Status | idle, cleaning, returning, charging, error, docked |
| Battery | Percentage |
| Mode | quiet, standard, turbo, max |
| Maps | Saved maps, rooms, zones, no-go areas, virtual walls |
| Room cleaning | Clean specific rooms by ID |
| Consumables | Filter, brush, mop pad (hours remaining) |
| History | Area, duration, date |

**Ecosystems:**
- **Roborock** — miio local API (well-documented), maps as gzip+deflate binary
- **Ecovacs (Deebot)** — XMPP cloud, partially reversed (deebot-client)
- **iRobot (Roomba)** — Local MQTT, maps cloud-only
- **Valetudo** — Open-source firmware, local MQTT, the gold standard for local control

---

## 7. Door Locks

| Capability | Details |
|-----------|---------|
| Lock/unlock | Command + state (locked, unlocked, jammed) |
| Door state | Open, closed (requires sensor) |
| User codes | Create, delete, modify PINs |
| User management | Per-user schedules, temporary codes |
| Auto-lock | Re-lock after timeout |
| Battery | Critical for wireless locks |
| Audit log | Every lock/unlock with timestamp + actor |

**Security requirements:**
- Elevated authentication for unlock commands (PIN, biometric, 2FA)
- Mandatory audit logging
- Network isolation (separate VLAN recommended)
- Z-Wave S2 Access Control key class is the most secure wireless option

**Ecosystems:** Yale, Schlage (Z-Wave), August/Yale (BLE+WiFi bridge), Nuki (BLE+local HTTP)

---

## 8. Sensors

| Type | Data | Typical Protocol |
|------|------|-----------------|
| Motion | Binary (detected/clear) + timeout | Zigbee, Z-Wave |
| Door/window | Binary (open/closed) + tamper | Zigbee, Z-Wave |
| Temperature | °C, ±0.1-0.5°C | Zigbee, BLE |
| Humidity | Relative %, often combined with temp | Zigbee, BLE |
| Water leak | Binary (wet/dry) | Zigbee, Z-Wave |
| Smoke/CO | Binary alarm + battery | Z-Wave (interconnect) |
| Air quality | PM2.5, PM10, VOC, CO2 (ppm) | WiFi |
| Light level | Illuminance (lux) | Zigbee |
| Vibration | Axis data + intensity | Zigbee (Aqara) |
| Pressure | Barometric (hPa) | Zigbee, BLE |

**Common attributes:** Battery %, last seen, signal strength, tamper detection.

**Reporting:** Zigbee sensors report on change + periodic heartbeat (1-4 hours).
BLE sensors broadcast periodically — need BLE gateway or ESP32 proxy.

---

## 9. Blinds / Curtains

| Capability | Details |
|-----------|---------|
| Open/close/stop | Basic commands |
| Position | 0-100% (semantics not standardized!) |
| Tilt angle | 0-100% or 0-180° (venetian blinds) |
| Battery | For battery-powered motors (IKEA FYRTUR) |
| Favorites | Stored positions on some motors |

**Position semantics trap:** Zigbee spec says 0=open, 100=closed. Most UIs invert this.
Your abstraction layer must normalize.

**Travel time:** Motors take 10-30s. Status updates may only give "moving" and "stopped"
rather than continuous position.

---

## 10. Energy Devices

| Device | Key Data | Protocol |
|--------|----------|----------|
| Solar inverter | Production W, daily/total kWh, string V/A | SunSpec Modbus TCP |
| Battery | SOC %, charge/discharge W, health | Modbus, vendor API |
| EV charger | Status, current A, energy kWh, schedule | OCPP (WebSocket), vendor API |
| Smart meter | Import/export W, daily kWh, tariff | P1 port (serial), vendor |

**SunSpec Modbus** is the standard for solar — standardized register maps over Modbus TCP.
Fronius, SMA, SolarEdge, Enphase all support it.

**OCPP** (Open Charge Point Protocol) is a WebSocket-based protocol for EV chargers.
Widely supported: ABB, Schneider, Wallbox, Easee.

**Tesla Powerwall** has a local REST API (authenticated).

---

## 11. Media Devices

| Capability | Details |
|-----------|---------|
| Transport | play, pause, stop, next, previous, seek |
| Volume | 0-100, mute |
| Now playing | Title, artist, album, art, duration, position |
| Source selection | Input switching |
| Grouping | Multi-room, stereo pairing |
| TTS | Text-to-speech announcements |

**Ecosystems:**
- **Sonos** — UPnP/SOAP local API, mDNS discovery, pychromecast
- **Chromecast** — pychromecast, mDNS, cast protocol
- **Apple TV** — pyatv (MediaRemote + AirPlay)
- **Samsung TV** — WebSocket API
- **LG TV** — WebOS WebSocket API (well-documented)
- **Roku** — REST ECP API (simple, reliable)

---

## 12. Manufacturer Ecosystem Reference

### Fully Local (no cloud needed)
| Ecosystem | Protocol | Library | Notes |
|-----------|----------|---------|-------|
| Shelly | REST + MQTT + WS + CoAP | `aioshelly` | Best-in-class local control |
| ESPHome | Native API (protobuf/TCP) | `aioesphome` | YAML-configured, custom devices |
| Tasmota | MQTT | `paho-mqtt` | 1000+ device templates |
| WLED | REST + MQTT + WS | HTTP client | LED strips, sACN/Art-Net |
| Hue (local) | CLIP v2 (HTTPS+SSE) | `aiohue` | Needs bridge, but fully local |
| Nuki | Local HTTP API | HTTP client | BLE lock with WiFi bridge |
| Kasa/Tapo | Local encrypted TCP | `python-kasa` | Reliable, no cloud needed |
| Xiaomi miio | Encrypted UDP | `python-miio` | Vacuums, purifiers, fans |
| OpenSprinkler | Local REST | HTTP client | Open source irrigation |

### Local with Cloud for Setup
| Ecosystem | Protocol | Library | Notes |
|-----------|----------|---------|-------|
| Tuya | Local encrypted UDP | `tinytuya` | Cloud needed for device keys only |
| Meross | Local MQTT | `meross-iot` | Cloud login for initial credentials |

### Cloud-Required
| Ecosystem | API | Library | Notes |
|-----------|-----|---------|-------|
| Ring/Blink | REST (reverse-engineered) | `ring-doorbell` | Fragile, Amazon hostile |
| Google Nest | SDM REST + Pub/Sub | official SDK | $5 fee, OAuth2 |
| Ecobee | REST + OAuth2 | `python-ecobee-api` | Stable |
| Home Connect | REST + OAuth2 | official SDK | Bosch/Siemens appliances |
| LG ThinQ | REST (reverse-engineered) | `wideq` | Unofficial |
| Samsung SmartThings | REST + OAuth2 | official SDK | Appliances, TVs |
