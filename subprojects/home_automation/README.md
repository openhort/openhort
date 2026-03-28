# Home Automation Integration — Research & Architecture

Investigation into open protocols, standards, and integration strategies for controlling
home devices (lights, cameras, appliances, sensors, etc.) from openhort.

## Documents

| Document | Description |
|----------|-------------|
| [01-protocols.md](01-protocols.md) | Complete survey of 20+ open home automation protocols |
| [02-matter-deep-dive.md](02-matter-deep-dive.md) | Technical deep dive into the Matter protocol |
| [03-platforms.md](03-platforms.md) | Home Assistant, OpenHAB, and other integration platforms |
| [04-device-categories.md](04-device-categories.md) | Device types, capabilities, and real-world ecosystems |
| [05-architecture.md](05-architecture.md) | Plugin architecture, trait model, isolation, and integration strategy |

## TL;DR — Recommended Strategy

1. **Use Home Assistant as a protocol bridge** — don't reimplement 200+ protocol adapters.
   Connect to HA's WebSocket API for device state and control.
2. **Support MQTT natively** — it's the lingua franca. ESPHome, Zigbee2MQTT, Tasmota,
   Shelly all speak it. One MQTT adapter covers hundreds of devices.
3. **Support Matter directly** (via python-matter-server) — it's the future standard.
4. **Build a trait-based device model** — OnOff, Brightness, Climate, Cover, etc.
   Match Matter's cluster model for forward compatibility.
5. **Overlay architecture** — openhort provides UI panels, automations, and remote access
   as an overlay on top of existing device control. Don't replace HA; augment it.
