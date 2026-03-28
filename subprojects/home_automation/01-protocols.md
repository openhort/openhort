# Home Automation Protocols — Complete Survey

## Protocol Landscape Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        APPLICATION LAYER                                │
│  Matter · Zigbee ZCL · Z-Wave CC · HomeKit HAP · KNX · DALI · ONVIF   │
├─────────────────────────────────────────────────────────────────────────┤
│                     MESSAGING / MIDDLEWARE                               │
│           MQTT · CoAP · UPnP/SOAP · REST/HTTP · WebSocket              │
├─────────────────────────────────────────────────────────────────────────┤
│                       NETWORK / TRANSPORT                                │
│     Thread · WiFi · Ethernet · BLE · Zigbee · Z-Wave · KNX TP/RF      │
├─────────────────────────────────────────────────────────────────────────┤
│                          PHYSICAL                                        │
│ IEEE 802.15.4 · IEEE 802.11 · EIA-485 · BLE Radio · Sub-GHz · PLC     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Matter (formerly CHIP / Connected Home over IP)

**Governing body:** Connectivity Standards Alliance (CSA)
**Version:** Matter 1.4 (Nov 2024); 1.0 released Oct 2022
**Transport:** IPv6 over WiFi, Thread, Ethernet; BLE for commissioning only

| Aspect | Detail |
|--------|--------|
| Port | UDP 5540 (operational), mDNS 5353 |
| Discovery | DNS-SD: `_matter._tcp` (operational), `_matterc._udp` (commissionable) |
| Encoding | TLV (Tag-Length-Value), compact binary |
| Security | PASE (SPAKE2+) for commissioning, CASE (Sigma) for operation, AES-128-CCM |
| Latency | 50-200ms WiFi, 100-500ms Thread |
| Max nodes | Unlimited (IPv6), practical ~250 per bridge |
| Openness | Spec available to CSA members, SDK open-source (Apache 2.0) |
| Ecosystem | 1000+ certified products; Apple, Google, Amazon, Samsung, IKEA, Hue |

**Key architecture:** Nodes → Endpoints → Clusters → Attributes/Commands/Events.
Device types composed from mandatory + optional clusters. Multi-admin via fabrics (up to 5).

**Interaction model:** Read, Write, Subscribe, Invoke (commands). Timed interactions for
security-critical operations (locks, garage doors). MRP provides reliable delivery over UDP.

See [02-matter-deep-dive.md](02-matter-deep-dive.md) for full protocol details.

---

## 2. Zigbee / Zigbee Cluster Library (ZCL)

**Governing body:** Connectivity Standards Alliance (CSA)
**Version:** Zigbee 3.0; Zigbee PRO 2023 (R23); ZCL 8
**Transport:** IEEE 802.15.4 at 2.4 GHz, 250 kbps

| Aspect | Detail |
|--------|--------|
| Topology | Mesh (coordinators, routers, end devices) |
| Addressing | 16-bit network + 64-bit EUI-64 |
| Channels | 11-26 in 2.4 GHz band |
| Range | 10-30m indoor per hop |
| Max devices | ~65,000 per network (practical: 200-300) |
| Encoding | Binary, tightly packed ZCL frames |
| Security | AES-128-CCM, network key + optional link keys |
| Latency | 15-30ms single hop |
| Ecosystem | 4,000+ certified products |

**Application layer (ZCL clusters):**
- On/Off (0x0006), Level Control (0x0008), Color Control (0x0300)
- Thermostat (0x0201), Door Lock (0x0101)
- Temperature (0x0402), Humidity (0x0405), Occupancy (0x0406)
- IAS Zone (0x0500) for security sensors
- Smart Energy metering (0x0702)

**Discovery:** Permit Joining window (60-254s), Device_annce broadcast, Active Endpoints
and Simple Descriptor queries for cluster enumeration.

**Security notes:** Zigbee 3.0 mandates install codes for secure joining, but the legacy
`ZigBeeAlliance09` trust center key is still a known weakness. Network key is shared
across all devices — compromise one, compromise all.

**Major devices:** Philips Hue, IKEA Tradfri/DIRIGERA, Aqara, Samsung SmartThings, Sengled

**Python:** `zigpy` (open source, async, used by Home Assistant ZHA integration)

---

## 3. Z-Wave / Z-Wave Long Range

**Governing body:** Z-Wave Alliance (Silicon Labs)
**Version:** Z-Wave 800 series; ITU-T G.9959
**Transport:** Sub-GHz ISM (908 MHz US, 868 MHz EU)

| Aspect | Detail |
|--------|--------|
| Topology | Mesh (max 4 hops), Z-Wave LR: star |
| Max nodes | 232 per network; LR: 4,000 |
| Range | 30-100m indoor (sub-GHz); LR: 1.6km LOS |
| Data rate | 9.6 / 40 / 100 kbps |
| Encoding | Binary, Command Class + Command ID + Params |
| Security | S2: ECDH (Curve25519) + AES-128-CCM; 3 key classes |
| Latency | 20-50ms single hop |
| Ecosystem | 4,400+ certified products |

**Advantages over Zigbee:** Sub-GHz penetrates walls better, less interference (no WiFi/BLE/microwave overlap), mandatory S2 security since 2017.

**Limitations:** Silicon Labs is sole chip vendor. Max 232 nodes. Proprietary until 2020.

**Command classes:** Binary Switch (0x25), Multilevel Switch (0x26), Door Lock (0x62),
Thermostat Mode (0x40), Meter (0x32), Notification (0x71), Central Scene (0x5B).

**SmartStart:** QR code pre-provisioning with DSK for zero-touch secure inclusion.

**Major devices:** Aeotec, Zooz, Fibaro, Yale/Schlage locks, Honeywell, Inovelli

**Python:** `zwave-js-server-python` (client for Z-Wave JS, used by Home Assistant)

---

## 4. Thread

**Governing body:** Thread Group
**Version:** Thread 1.3 (2022)
**Transport:** IEEE 802.15.4 at 2.4 GHz (same PHY as Zigbee)

| Aspect | Detail |
|--------|--------|
| Key feature | Native IPv6 via 6LoWPAN |
| Topology | Mesh (max 32 routers, ~16K end devices) |
| Application layer | **None** — transport only; Matter runs on top |
| Discovery | MLE, mDNS proxy via Border Router |
| Security | AES-128-CCM at MAC layer, DTLS for commissioning |
| Border Router | Required to bridge to WiFi/Ethernet |

Thread is not a competitor to Zigbee at the application level — it's a **network transport**
that Matter uses. Devices speak Matter's data model; Thread provides the mesh network.

**Border Routers:** Apple HomePod/TV 4K, Google Nest Hub 2nd gen, Nest WiFi Pro,
Nanoleaf, Eve, Aqara Hub M3.

**Open source:** OpenThread (BSD-3, maintained by Google)

---

## 5. Bluetooth Low Energy / Bluetooth Mesh

**Governing body:** Bluetooth SIG
**Version:** BLE 5.4; Bluetooth Mesh 1.1

### BLE (point-to-point)

| Aspect | Detail |
|--------|--------|
| Frequency | 2.4 GHz, 40 channels |
| Data rate | 1 Mbps (4.x), 2 Mbps (5.0+), 125/500 kbps coded (long range) |
| Range | 10-30m typical, 400m+ coded PHY |
| Protocol | GATT (services + characteristics) |
| Discovery | Advertising on channels 37/38/39 |
| Security | LE Secure Connections (ECDH P-256), AES-128-CCM |
| Max MTU | 23 bytes default, up to 512 negotiated |

Used in smart home primarily for: device setup/commissioning, beacons, proximity sensors,
Govee lights, SwitchBot devices, Xiaomi sensors.

### Bluetooth Mesh

Flooding-based mesh on top of BLE advertising. Managed flooding with TTL and message caching.
Mesh 1.1 adds Directed Forwarding (path-based routing) to reduce flooding overhead.

| Aspect | Detail |
|--------|--------|
| Nodes | Up to 32,767 per network |
| Models | Generic OnOff, Level, Lightness, CTL, HSL, Sensor |
| Security | Network key (flood encryption) + Application key (per-model) |
| Provisioning | PB-ADV (advertising) or PB-GATT |

Used commercially for lighting control in offices/retail. Limited home adoption.

**Python:** `bleak` (BLE, cross-platform, async)

---

## 6. KNX

**Governing body:** KNX Association
**Standard:** EN 50090, ISO/IEC 14543-3
**Transport:** Twisted pair bus (primary), powerline, RF, IP

| Aspect | Detail |
|--------|--------|
| TP bus | 9600 bps, 2-wire, max 64 devices/line, 57,600 total |
| IP | KNXnet/IP: UDP port 3671 (multicast 224.0.23.12) |
| Addressing | Area.Line.Device (4.4.8 bit) |
| Encoding | Binary datapoint types (DPT) |
| Security | KNX Secure (AES-128-CCM) added in 2019 |

**The professional building automation standard in Europe.** Electricians install KNX wiring
during construction. Over 8,000 certified products from 500+ manufacturers.

Not practical for retrofit/consumer use. Relevant for openhort if targeting commercial buildings
or high-end residential installations.

**KNXnet/IP tunneling** allows IP-based control of KNX installations from standard computers.

**Python:** `xknx` (async, full KNXnet/IP client)

---

## 7. MQTT

**Governing body:** OASIS
**Version:** MQTT 5.0 (2019); 3.1.1 (2014) still dominant
**Transport:** TCP port 1883, TLS port 8883, WebSocket port 9001

| Aspect | Detail |
|--------|--------|
| Model | Publish/Subscribe via broker |
| QoS | 0 (at most once), 1 (at least once), 2 (exactly once) |
| Retained | Yes — last message stored per topic |
| LWT | Last Will and Testament for disconnect detection |
| Payload | Agnostic (JSON common, binary supported) |
| MQTT 5.0 | Shared subscriptions, message expiry, topic aliases, user properties |

**The universal IoT messaging protocol.** Nearly every smart home device or bridge can
speak MQTT. It's the most practical single protocol to support.

**MQTT in smart home:**
- Zigbee2MQTT: Zigbee coordinator → MQTT topics per device
- Tasmota: ESP devices → MQTT
- ESPHome: optional MQTT alongside native API
- Shelly: built-in MQTT support
- Home Assistant: MQTT discovery (auto-creates entities from MQTT topics)

**HA MQTT Discovery format:**
```
homeassistant/light/kitchen/config → {"name": "Kitchen", "stat_t": "zigbee2mqtt/kitchen/state", ...}
```

**Brokers:** Mosquitto (C, lightweight, standard), EMQX (Erlang, clustered), NanoMQ, HiveMQ

**Python:** `aiomqtt` (async, modern), `paho-mqtt` (sync/callback, mature)

### MQTT-SN (Sensor Networks)

Variant for constrained devices (UDP, no TCP required). Port 1883/UDP.
Uses topic IDs (2 bytes) instead of topic strings. Gateway bridges to standard MQTT broker.
Rarely used directly — most sensor devices use Zigbee/Thread/BLE instead.

---

## 8. CoAP (Constrained Application Protocol)

**Governing body:** IETF (CoRE working group)
**Standard:** RFC 7252
**Transport:** UDP port 5683, DTLS port 5684

| Aspect | Detail |
|--------|--------|
| Model | RESTful (GET/PUT/POST/DELETE) like HTTP |
| Encoding | CBOR (binary JSON), or any |
| Observe | Subscribe to resource changes (RFC 7641) |
| Block | Chunked transfers (RFC 7959) |
| Discovery | `/.well-known/core` (RFC 6690) |
| Multicast | IPv6 multicast for group operations |
| Security | DTLS 1.2, OSCORE (RFC 8613) for object security |

Designed as "HTTP for constrained devices." Used internally by Thread for management,
by Shelly Gen 1 for state updates, and as the basis for OCF/IoTivity.

**Python:** `aiocoap` (async, full implementation)

---

## 9. OCF / IoTivity

**Governing body:** Open Connectivity Foundation
**Transport:** CoAP over UDP/TCP, DTLS/TLS

Resource model where everything is a REST resource. Had strong backing (Intel, Samsung,
Qualcomm) but lost momentum to Matter. IoTivity project is in maintenance mode.

Multicast discovery on 224.0.1.187:5683 (IPv4) / ff02::158:5683 (IPv6).

Not recommended for new integration work — Matter has won this space.

---

## 10. DALI (Digital Addressable Lighting Interface)

**Governing body:** DiiA (Digital Illumination Interface Alliance)
**Standard:** IEC 62386
**Version:** DALI-2; D4i (DALI for IoT)

| Aspect | Detail |
|--------|--------|
| Transport | Dedicated 2-wire bus, 16V, Manchester encoding |
| Data rate | 1200 bps (forward), 2400 bps (backward) |
| Addressing | 64 individual + 16 group + broadcast per bus |
| Commands | Direct arc power (0-254), scenes (0-15), fade time |
| DALI-2 | Device types 1-8 (LED, emergency, sensors, etc.) |
| D4i | Energy metering, diagnostics over DALI bus |

Professional lighting protocol, standard in commercial buildings. Each luminaire has a
DALI driver. DALI-2 adds sensors, pushbuttons, and energy monitoring.

**Gateway access:** DALI-to-IP gateways (e.g., Wago, Helvar, Tridonic) expose DALI bus
via REST/MQTT/KNX. Control DALI via the gateway's IP interface.

Not directly relevant for typical home automation unless retrofitting commercial space.

---

## 11. DMX512 / sACN / Art-Net

Entertainment and stage lighting protocols. Relevant for home theater, RGB LED installations,
and architectural lighting.

### DMX512
- **Transport:** RS-485, unidirectional, daisy-chain
- **Data:** 512 channels per universe, 8-bit values (0-255)
- **Refresh:** ~44 Hz full universe (250 kbps)
- **No feedback:** controller has no way to know device state

### sACN (Streaming ACN, E1.31)
- DMX512 data over Ethernet/UDP
- Multicast: 239.255.x.x per universe, port 5568
- Supports 63,999 universes (vs 1 per DMX wire)
- **Most practical for home integration** — standard UDP, easy to generate

### Art-Net
- Similar to sACN — DMX over UDP, port 6454
- Broadcast-based discovery
- Widely supported by LED controllers (WLED, etc.)

**For RGB LED strips:** WLED firmware on ESP32 speaks Art-Net/sACN/E1.31 + REST + MQTT.
Easiest path: MQTT or REST to WLED devices.

---

## 12. ONVIF (Cameras)

**Governing body:** ONVIF
**Transport:** HTTP/HTTPS (SOAP/XML), RTSP/RTP for video

| Aspect | Detail |
|--------|--------|
| Discovery | WS-Discovery: UDP multicast 239.255.255.250:3702 |
| Control | SOAP/XML web services over HTTP |
| Video | RTSP (port 554), RTP (dynamic ports) |
| Profiles | S (streaming), T (advanced streaming), G (recording), C (access), A (access), M (metadata) |
| PTZ | SOAP commands for pan/tilt/zoom, absolute/relative/continuous |
| Events | WS-BaseNotification, pull-point subscription |
| Auth | HTTP Digest, WS-Security UsernameToken |

**The camera interoperability standard.** Supported by Axis, Hikvision, Dahua, Reolink,
Amcrest, Hanwha, and hundreds of others.

**Profile S (streaming)** is the most relevant: GetStreamUri → RTSP URL.
**Profile T** adds H.265 and improved metadata streaming.

**Real-world gotcha:** Many cheap cameras claim ONVIF but implement only a subset.
RTSP URLs are not standardized — each manufacturer uses different paths.

**Best approach:** Use **go2rtc** as a universal camera proxy. It speaks RTSP, ONVIF,
HomeKit, and can output WebRTC/HLS/MJPEG. Feed any camera into go2rtc, get a
standardized stream out.

**Python:** `onvif-zeep` or `python-onvif-zeep` (SOAP client for ONVIF services)

---

## 13. HomeKit Accessory Protocol (HAP)

**Governing body:** Apple
**Transport:** TCP/HTTP (IP accessories), BLE GATT (BLE accessories)

| Aspect | Detail |
|--------|--------|
| Discovery | mDNS/Bonjour `_hap._tcp` |
| Security | SRP (Secure Remote Password) for pairing, Ed25519 + ChaCha20-Poly1305 |
| Encoding | TLV8 (pairing), JSON (characteristics) |
| Model | Accessories → Services → Characteristics |

**Non-commercial spec is published** — anyone can build a HomeKit accessory without MFi
certification for non-commercial use. HomeBridge exploits this to bridge thousands of
devices into HomeKit.

**HomeBridge:** Node.js platform that creates virtual HomeKit accessories for non-HomeKit
devices. 2,000+ plugins. Alternative to Home Assistant for Apple-focused users.

**Python:** `HAP-python` (HomeKit accessory library), `aiohomekit` (HomeKit controller)

**Strategic note:** With Matter, HomeKit is becoming less relevant as a protocol.
New devices target Matter; HomeKit support comes via Matter's multi-admin.

---

## 14. UPnP / SSDP

**Governing body:** OCF (originally UPnP Forum / Microsoft)
**Transport:** UDP multicast 239.255.255.250:1900 (SSDP), HTTP (SOAP)

Legacy protocol for device discovery and control. Still used by:
- Sonos speakers (SOAP/UPnP for control)
- Samsung TVs (older models)
- DLNA media streaming
- Network routers (IGD for port forwarding)

**Discovery (SSDP):**
```
M-SEARCH * HTTP/1.1
HOST: 239.255.255.250:1900
MAN: "ssdp:discover"
ST: ssdp:all
MX: 3
```

Largely superseded by mDNS/DNS-SD for modern devices. Still needed for Sonos integration.

---

## 15. Modbus

**Governing body:** Modbus Organization (CLPA)
**Transport:** RS-485 serial (RTU), TCP/IP (Modbus TCP port 502)

| Aspect | Detail |
|--------|--------|
| Model | Master/slave, register-based |
| RTU | Serial 9600-115200 baud, max 247 devices |
| TCP | Port 502, no authentication (!), unit ID for gateway addressing |
| Registers | 16-bit holding/input registers, 1-bit coils/discrete inputs |
| Functions | Read Coils (01), Read Registers (03), Write Single (05/06), Write Multiple (15/16) |

**The industrial protocol.** Used by:
- Solar inverters (SunSpec standard register maps)
- EV chargers (some)
- Heat pumps
- Battery management systems
- Smart meters

SunSpec Alliance defines standardized register maps for solar/energy devices on top of Modbus.
If your device has a SunSpec-compliant inverter, you can read production data via Modbus TCP.

**Security:** None. Modbus TCP has zero authentication. Must be on an isolated network.

**Python:** `pymodbus` (async, supports RTU/TCP/UDP, widely used)

---

## 16. EnOcean

**Governing body:** EnOcean Alliance
**Standard:** ISO/IEC 14543-3-10/11
**Transport:** Sub-1 GHz (868/902/928 MHz)

**Unique feature:** Energy harvesting — no batteries. Powered by:
- Kinetic energy (pushbutton switches)
- Solar/indoor light (sensors)
- Thermal gradients (radiator valves)

| Aspect | Detail |
|--------|--------|
| Range | 30m indoor, 300m outdoor |
| Data rate | 125 kbps |
| Telegram size | Very short (14 bytes typical) |
| Encoding | EnOcean Equipment Profiles (EEP) |
| Security | AES-128 (optional, rolling code) |

Niche but clever — perfect for switches/sensors where wiring is impossible and battery
replacement is undesirable. Common in European building automation.

**Gateway:** EnOcean USB dongles + software (e.g., Eltako, NodOn). Home Assistant has
an EnOcean integration.

---

## 17. Insteon

**Transport:** Dual-band (RF 915 MHz + powerline)
**Status:** Company went bankrupt in 2022. Servers shut down. Community revival via
open-source Insteon hub firmware. **Not recommended for new installations.**

---

## 18. Wi-SUN

**Governing body:** Wi-SUN Alliance
**Transport:** Sub-GHz IEEE 802.15.4g, mesh, IPv6

Smart utility/city mesh networking. Used for smart meters, street lighting, smart grid.
Not consumer-facing. Mentioned for completeness — relevant if integrating with utility
smart meters.

---

## 19. LwM2M (Lightweight M2M)

**Governing body:** OMA SpecWorks
**Transport:** CoAP over UDP/TCP

Device management protocol for IoT. Defines standardized object models for sensors,
actuators, and device management. Used in carrier IoT (NB-IoT, LTE-M) deployments.
Less relevant for home automation, more for fleet management of industrial IoT.

---

## Protocol Selection Matrix

| Use Case | Primary | Secondary | Notes |
|----------|---------|-----------|-------|
| Lights (bulbs) | Zigbee, Matter | WiFi (Tuya), BLE (Govee) | Zigbee for existing, Matter for new |
| Switches/dimmers | Z-Wave, Zigbee, Matter | WiFi | Z-Wave best for wall switches (sub-GHz range) |
| Sensors | Zigbee, Thread/Matter | BLE, EnOcean | Battery life matters → avoid WiFi |
| Door locks | Z-Wave (S2), Matter | BLE | Z-Wave S2 Access Control key class |
| Cameras | ONVIF/RTSP | WebRTC (Matter 1.4) | go2rtc as universal proxy |
| Thermostats | Z-Wave, Matter | WiFi (cloud APIs) | Ecobee/Nest are cloud-dependent |
| Appliances | Cloud APIs | Matter (1.2+) | Mostly cloud-only today |
| LED strips | WiFi (WLED) | sACN/Art-Net | WLED + MQTT is the sweet spot |
| Energy/solar | Modbus TCP | WiFi (vendor APIs) | SunSpec for standardized access |
| Building-grade | KNX | DALI (lighting) | Professional installation only |

## Integration Priority (for openhort)

**Tier 1 — Must have:**
1. MQTT (covers Zigbee2MQTT, Tasmota, Shelly, ESPHome, and HA bridge)
2. Home Assistant WebSocket API (instant access to 2,000+ integrations)
3. ONVIF/RTSP (cameras — core openhort use case)

**Tier 2 — Should have:**
4. Matter (via python-matter-server — the future)
5. Shelly native (REST/WebSocket — popular, fully local, no hub needed)
6. Tuya local (via tinytuya — covers hundreds of cheap WiFi devices)

**Tier 3 — Nice to have:**
7. Hue native (aiohue — for users without HA)
8. KNX (xknx — for building automation)
9. sACN/Art-Net (for entertainment lighting)
10. Modbus TCP (for solar/energy monitoring)
