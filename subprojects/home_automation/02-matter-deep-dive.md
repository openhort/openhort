# Matter Protocol — Deep Technical Dive

## Protocol Stack

```
┌────────────────────────────────────────────┐
│           Application (Device Types)        │
│  Lights · Locks · Thermostats · Cameras    │
├────────────────────────────────────────────┤
│         Data Model (Clusters)               │
│  OnOff · Level · Color · DoorLock · ...    │
├────────────────────────────────────────────┤
│         Interaction Model                   │
│  Read · Write · Subscribe · Invoke         │
├────────────────────────────────────────────┤
│      Security (Session Layer)               │
│  PASE (commissioning) · CASE (operation)   │
├────────────────────────────────────────────┤
│       Transport (MRP / TCP / BTP)           │
│  Reliable messaging over UDP / TCP / BLE   │
├────────────────────────────────────────────┤
│         Network (IPv6)                      │
│  Thread (802.15.4) · WiFi · Ethernet       │
└────────────────────────────────────────────┘
```

---

## 1. Network Layer

### Thread (for low-power battery devices)
- IEEE 802.15.4 at 2.4 GHz, 250 kbps
- IPv6-native via 6LoWPAN adaptation
- Mesh topology: routers forward for sleepy end devices
- Requires Thread Border Router (TBR) to bridge to WiFi/Ethernet
- Apple TV 4K, HomePod Mini, Google Nest Hub 2nd gen serve as TBRs
- Thread 1.3+ required for Matter

### WiFi (for mains-powered, higher-bandwidth devices)
- Standard 802.11 infrastructure
- Higher power → not for battery devices
- Devices get standard IPv6 addresses on local network
- No special router needed

### Ethernet (for bridges, hubs, media devices)
- Direct IPv6 connectivity, simplest transport
- Used primarily by bridges and controllers

---

## 2. Transport Layer

### MRP (Matter Reliable Protocol) — Primary
- Reliability on top of UDP
- Message counters, ACKs, retransmissions
- Configurable intervals: 300ms active, 5000ms idle for sleepy devices
- Messages encrypted at session layer before MRP

### TCP — Large transfers
- OTA firmware updates, large data reads
- Standard TCP, no TLS (Matter has own encryption)

### BTP (Bluetooth Transport Protocol) — Commissioning only
- BLE GATT-based for initial key exchange
- Not used for ongoing operational communication

---

## 3. Security Layer

### PASE (Passcode-Authenticated Session Establishment)
- Used during commissioning only
- Based on SPAKE2+ (augmented password-authenticated key exchange)
- Passcode from QR code or manual pairing code (27-bit)
- Establishes temporary encrypted channel for provisioning

### CASE (Certificate-Authenticated Session Establishment)
- All post-commissioning (operational) communication
- Based on Sigma protocol (3-pass mutual authentication)
- Both sides present NOC (Node Operational Certificate) chains
- Session keys: AES-128-CCM encryption, per-message counter
- Sessions are resumable (quick re-establishment without full handshake)

### Certificate Chain (PKI)
```
Root CA (ecosystem controller: Apple/Google/etc.)
  └── ICAC (Intermediate CA, optional)
       └── NOC (Node Operational Certificate)
            Contains: Fabric ID + Node ID
```
- Compact TLV encoding (not X.509 DER)
- Each device holds multiple NOCs (one per fabric) → multi-admin

### Group Security
- Symmetric group keys for multicast commands (e.g., "all lights off")
- Distributed via Group Key Management cluster
- AES-128-CCM with epoch keys, rotated periodically
- IPv6 multicast delivery, no individual ACK

---

## 4. Data Model

### Hierarchy

```
Node (physical device)
├── Endpoint 0 (Root / Utility)
│   ├── Basic Information Cluster
│   ├── General Commissioning Cluster
│   ├── Network Commissioning Cluster
│   ├── OTA Software Update Cluster
│   ├── Access Control Cluster
│   └── Group Key Management Cluster
├── Endpoint 1 (Application — e.g., a light)
│   ├── On/Off Cluster (0x0006)
│   │   ├── Attributes: OnOff (bool), GlobalSceneControl, OnTime, OffWaitTime
│   │   ├── Commands: On(), Off(), Toggle(), OnWithTimedOff()
│   │   └── Events: (none)
│   ├── Level Control Cluster (0x0008)
│   │   ├── Attributes: CurrentLevel (0-254), MinLevel, MaxLevel, OnLevel
│   │   └── Commands: MoveToLevel(), Move(), Step(), Stop()
│   └── Color Control Cluster (0x0300)
│       ├── Attributes: CurrentHue, CurrentSaturation, ColorTemperatureMireds
│       └── Commands: MoveToHue(), MoveToSaturation(), MoveToColorTemperature()
├── Endpoint 2 (second application — e.g., second socket in a dual-plug)
│   └── ...
```

### Clusters
- Defined by numeric IDs (On/Off=0x0006, Level=0x0008, Color=0x0300, etc.)
- Server role (device) and client role (controller)
- **Attributes:** typed data (bool, uint8, string, structs, lists)
- **Commands:** RPC calls with request/response structures
- **Events:** timestamped log entries (switch pressed, alarm triggered)
- Quality flags: nullable, persistent, timed-write-required

### Device Types
Define which clusters an endpoint must implement:
- "Dimmable Light" = On/Off (server) + Level Control (server) + utility clusters
- Conformance levels: mandatory, optional, provisional
- Single endpoint can implement multiple device types

---

## 5. Interaction Model

### Read / Subscribe
- **Read Request → Report Data** (one-time pull)
- **Subscribe Request → Report Data** (ongoing push, min/max interval negotiated)
- Client sends SubscriptionKeepAlive if no reports; server confirms

### Write
- **Write Request → Write Response**
- Supports timed writes (for security-sensitive operations)
- Batch writes (multiple attributes in one message)

### Invoke (Commands)
- **Invoke Request → Invoke Response**
- Timed invoke for security-critical operations (door locks, garage doors)
- Two-phase: send TimedRequest with timeout, then actual Invoke within window
- Prevents replay attacks on security operations

---

## 6. Key Concepts

### Fabrics (Multi-Admin)
- A fabric = one ecosystem's administrative domain
- Each fabric has its own Root CA, NOCs, ACLs
- Device can join up to 5 fabrics simultaneously
- Each fabric sees its own node IDs
- ACLs are per-fabric — Fabric A cannot modify Fabric B's rules
- This enables one light controlled by Apple Home + Google Home + Alexa

### Commissioning Flow
1. **Discovery:** BLE advertisement, WiFi Soft-AP, or on-network
2. **QR Code / Manual Code:** Discriminator (12-bit) + Passcode (27-bit) + Vendor/Product ID
   - QR format: `MT:` prefix, base-38 encoded
   - Manual: 11-digit or 21-digit number
3. **PASE session:** Encrypted channel using passcode
4. **Device attestation:** Verify DAC (Device Attestation Certificate) chain
   - PAA → PAI → DAC, verified against Distributed Compliance Ledger
5. **Operational credentials:** Provision NOC, Root CA cert, Fabric ID, Node ID
6. **Network provisioning:** WiFi credentials or Thread dataset
7. **Complete:** Device on operational network with valid CASE credentials

### Operational Discovery (DNS-SD)
- Commissionable: `_matterc._udp` with discriminator, vendor/product in TXT records
- Operational: `_matter._tcp` with compressed fabric+node ID
- Thread devices discovered via Border Router's mDNS proxy

### Binding and Grouping
- **Binding:** Direct device-to-device association (switch → light, no controller needed)
- **Groups:** IPv6 multicast, 16-bit Group ID, fire-and-forget
- Group keys managed by Group Key Management cluster

### Scenes
- Stored configurations of cluster attributes, recalled atomically
- Stored on-device in Scenes Management cluster
- Each scene belongs to a group, has a scene ID
- RecallScene restores state, StoreScene captures current state
- Transition time for smooth changes

### OTA Updates
- OTA Provider cluster (hub/cloud) announces + serves firmware
- OTA Requestor cluster (device) queries + applies updates
- BDX (Bulk Data Transfer) protocol over TCP for large downloads
- Supports deferred updates, staged rollouts

---

## 7. Supported Device Types by Version

### Matter 1.0 (October 2022)
- Lights: On/Off, Dimmable, Color Temp, Extended Color
- Switches: On/Off, Dimmer, Color Dimmer, Generic Switch
- Thermostats/HVAC: Thermostat cluster, Fan Control
- Door Locks: Lock/Unlock, credentials, user management, timed invoke required
- Window Coverings: Position + Tilt
- Sensors: Temperature, Humidity, Occupancy, Light, Pressure, Flow, Contact
- Media: Playback, Input, Content Launcher, Audio Output, Channel, Keypad
- Bridges: Aggregator endpoint for bridged devices

### Matter 1.1 (May 2023)
- ICD (Intermittently Connected Devices) — formal framework for sleepy/battery devices
- Check-in protocol for ICDs
- Bug fixes and clarifications

### Matter 1.2 (October 2023)
- Fans, Air Purifiers, Room Air Conditioners
- Smoke/CO Alarms, Air Quality Sensors, Concentration Sensors (PM2.5, PM10, NO2, etc.)
- Appliances (basic): Refrigerators, Laundry Washers, Dishwashers, Robot Vacuums (basic)
- Mode clusters, Operational State cluster

### Matter 1.3 (May 2024)
- Energy management: EVSE (EV charger), Power/Energy Measurement
- Appliances: Ovens, Cooktops, Range Hoods, Microwave Ovens, Laundry Dryers
- Water Leak and Rain Sensors
- Enhanced multi-admin, fabric sync
- Scene management overhaul

### Matter 1.4 (November 2024)
- **Cameras:** AV Stream Management, WebRTC transport, snapshot, two-way audio
- **Robot Vacuums:** Enhanced with ServiceArea cluster (room selection), clean modes
- Water Heater Management
- Thread 1.3+ enhancements, shared Thread network credentials
- Enhanced ICD (Long Idle Time — devices sleeping hours/days)
- Network infrastructure management (Thread Border Router, WiFi AP as device types)

### Still Missing / Coming
- Security systems (alarm panels, zones)
- Garage door openers (no official device type yet)
- Irrigation/sprinkler systems
- Audio streaming (control only, no media transport)
- Complex automations (Matter controls devices, not rules)
- Cloud recording for cameras

---

## 8. Building a Matter Controller in Python

### Using python-matter-server (recommended)

```python
from matter_server.client import MatterClient
import asyncio

async def main():
    client = MatterClient("ws://localhost:5580/ws")
    await client.connect()

    # Commission via QR code
    await client.commission_with_code("MT:Y.K9042C00KA0648G00")

    # List nodes
    nodes = await client.get_nodes()
    for node in nodes:
        print(f"Node {node.node_id}: {node.name}")

    # Toggle a light (node 1, endpoint 1)
    from chip.clusters import Objects as clusters
    await client.send_command(
        node_id=1,
        endpoint_id=1,
        command=clusters.OnOff.Commands.Toggle()
    )

    # Read attribute
    result = await client.read_attribute(
        node_id=1,
        attribute_path="1/6/0"  # endpoint/cluster/attribute
    )

    # Subscribe to changes
    await client.subscribe_attribute(
        node_id=1,
        attribute_path="1/6/0",
        callback=lambda value: print(f"Light: {value}")
    )

asyncio.run(main())
```

### Using CHIP Python bindings directly (lower level)

```python
import chip.native
from chip.ChipDeviceCtrl import ChipDeviceController

chip.native.Init()
devCtrl = ChipDeviceController(
    opServerPort=5540, keypair=None, fabricId=1, nodeId=1
)

# Commission over BLE-WiFi
devCtrl.ConnectBLE(discriminator=3840, setupPinCode=20202021, nodeid=2)

# Send command
from chip.clusters import Objects as C
devCtrl.SendCommand(nodeid=2, endpoint=1, payload=C.OnOff.Commands.On())

# Read attribute
result = devCtrl.ReadAttribute(nodeid=2, attributes=[(1, C.OnOff.Attributes.OnOff)])
```

---

## 9. Building a Matter Bridge

Expose non-Matter devices (Zigbee, Z-Wave, proprietary) as Matter endpoints:

```
Matter Bridge Device
├── Endpoint 0: Root (utility clusters)
├── Endpoint 1: Aggregator (device type 0x000E — indicates bridge)
├── Endpoint 3: Bridged Light A (On/Off + Bridged Device Basic Info)
├── Endpoint 4: Bridged Light B (Dimmable + Bridged Device Basic Info)
├── Endpoint 5: Bridged Sensor (Temperature + Bridged Device Basic Info)
└── ...dynamic endpoints per bridged device
```

- Aggregator on Endpoint 1 signals "this is a bridge"
- Each bridged device has **Bridged Device Basic Information** cluster
- `Reachable` attribute signals device availability
- Dynamic endpoint addition/removal as devices join/leave native protocol
- Bridge translates: Matter command → native protocol → device → state → Matter report

### Thread Border Router Requirements
- Hardware: 802.15.4 USB radio (Nordic nRF52840, Silicon Labs EFR32)
- Software: OpenThread Border Router (OTBR)
- Functions: IPv6 routing, mDNS proxy, multicast forwarding, credential management
- DIY: Raspberry Pi + nRF52840 dongle + OTBR Docker container

---

## 10. Performance and Limitations

| Metric | Value |
|--------|-------|
| Command latency (WiFi) | 50-200ms |
| Command latency (Thread) | 100-500ms |
| Subscription interval | 1s - hours (negotiated) |
| Commissioning time | 15-60 seconds |
| Max subscriptions per device | 3-10 (implementation-dependent) |
| Max endpoints per node | ~250 practical for bridges |
| MRP message size | ~1280 bytes (IPv6 MTU) |
| Group multicast latency | Near-instant (WiFi), 100-300ms (Thread) |

### Key Limitations
1. **Bridge overhead:** Most existing devices need a bridge → added latency + failure point
2. **Incomplete coverage:** Security panels, garage doors, irrigation not yet standardized
3. **Resource constraints:** Multi-fabric subscriptions are heavy for Thread battery devices
4. **Ecosystem inconsistency:** Each app (Apple/Google/Amazon) exposes different feature subsets
5. **No automation standard:** Matter controls devices but doesn't define automation rules
