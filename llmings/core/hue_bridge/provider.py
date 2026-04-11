"""Hue Bridge llming — Philips Hue smart light discovery, auth, and control."""

from __future__ import annotations

import json
import ssl
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from hort.llming import Llming, Power, PowerType


# Hue bridges use self-signed certs
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_DISCOVER_URL = "https://discovery.meethue.com/"
_LINK_DEVICETYPE = "openhort#hort"


def _hue_get(url: str, timeout: int = 5) -> Any:
    """GET a Hue API endpoint, returns parsed JSON."""
    req = Request(url, method="GET")
    with urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
        return json.loads(resp.read())


def _hue_post(url: str, body: dict[str, Any], timeout: int = 5) -> Any:
    """POST to a Hue API endpoint, returns parsed JSON."""
    data = json.dumps(body).encode()
    req = Request(url, data=data, method="POST",
                  headers={"Content-Type": "application/json"})
    with urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
        return json.loads(resp.read())


class HueBridge(Llming):
    """Discovers Hue Bridge, handles link-button auth, controls lights."""

    def activate(self, config: dict[str, Any]) -> None:
        self._bridge_ip: str | None = config.get("bridge_ip")
        self._api_key: str | None = None
        self._lights: dict[str, Any] = {}
        self._groups: dict[str, Any] = {}
        self._sensors: dict[str, Any] = {}
        self._bridge_name: str | None = None
        self._auth_state: str = "not_configured"  # not_configured | pairing | ok | error
        self._auth_message: str = ""
        # Try to load stored key (sync wrapper — store may not be async-ready here)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._restore_on_activate())
            else:
                loop.run_until_complete(self._restore_on_activate())
        except Exception:
            pass
        self.log.info("Hue Bridge plugin activated")

    async def _restore_on_activate(self) -> None:
        """Load stored credentials and poll if available."""
        if await self._load_stored_key():
            self.poll_lights()

    def deactivate(self) -> None:
        self.log.info("Hue Bridge plugin deactivated")

    # ── Lifecycle ───────────────────────────────────────────────────

    async def _load_stored_key(self) -> bool:
        """Try to load API key from store."""
        if not self.store:
            return False
        key = await self.store.get("hue_api_key")
        ip = await self.store.get("hue_bridge_ip")
        if key and ip:
            self._api_key = key
            self._bridge_ip = ip
            self._auth_state = "ok"
            self.log.info("Loaded stored Hue API key for bridge at %s", ip)
            return True
        return False

    async def _save_key(self, ip: str, key: str) -> None:
        """Persist API key."""
        if self.store:
            await self.store.put("hue_api_key", key)
            await self.store.put("hue_bridge_ip", ip)

    # ── Discovery ───────────────────────────────────────────────────

    def _discover_bridge(self) -> str | None:
        """Find bridge IP via Hue cloud discovery + mDNS fallback."""
        # Cloud discovery (fast, reliable)
        try:
            bridges = json.loads(
                urlopen(_DISCOVER_URL, timeout=5).read()
            )
            if bridges and isinstance(bridges, list):
                ip = bridges[0].get("internalipaddress")
                if ip:
                    self.log.info("Discovered Hue Bridge at %s (cloud)", ip)
                    return ip
        except Exception:
            pass

        # mDNS fallback — try common IPs on the local subnet
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            prefix = ".".join(local_ip.split(".")[:3])
            # Hue bridges often respond on port 443
            for last in range(1, 255):
                ip = f"{prefix}.{last}"
                try:
                    resp = urlopen(
                        f"https://{ip}/api/0/config",
                        context=_SSL_CTX, timeout=0.3,
                    )
                    data = json.loads(resp.read())
                    if "bridgeid" in data:
                        self.log.info("Discovered Hue Bridge at %s (scan)", ip)
                        return ip
                except Exception:
                    continue
        except Exception:
            pass

        return None

    # ── Auth ────────────────────────────────────────────────────────

    def _try_pair(self, ip: str) -> str | None:
        """Attempt link-button pairing. Returns API key or None."""
        try:
            result = _hue_post(
                f"https://{ip}/api",
                {"devicetype": _LINK_DEVICETYPE},
            )
            if isinstance(result, list) and result:
                entry = result[0]
                if "success" in entry:
                    return entry["success"]["username"]
                if "error" in entry:
                    # error type 101 = link button not pressed
                    self.log.debug("Pairing response: %s", entry["error"].get("description"))
        except Exception as e:
            self.log.warning("Pairing request failed: %s", e)
        return None

    # ── Polling ─────────────────────────────────────────────────────

    def poll_lights(self) -> None:
        """Scheduler job — fetch light, group, and sensor state from bridge."""
        if not self._api_key or not self._bridge_ip:
            return
        try:
            base = f"https://{self._bridge_ip}/api/{self._api_key}"
            self._lights = _hue_get(f"{base}/lights")
            self._groups = _hue_get(f"{base}/groups")
            self._sensors = _hue_get(f"{base}/sensors")
            config = _hue_get(f"{base}/config")
            self._bridge_name = config.get("name", "Hue Bridge")
            self._auth_state = "ok"
        except Exception as e:
            self.log.warning("Failed to poll Hue: %s", e)
            self._auth_state = "error"
            self._auth_message = str(e)

    # ── Pulse ───────────────────────────────────────────────────────

    def get_pulse(self) -> dict[str, Any]:
        lights_summary = []
        for lid, light in self._lights.items():
            state = light.get("state", {})
            lights_summary.append({
                "id": lid,
                "name": light.get("name", f"Light {lid}"),
                "on": state.get("on", False),
                "brightness": state.get("bri", 0),
                "reachable": state.get("reachable", False),
            })
        # Group sensors by their associated motion sensor (presence + light + temp)
        sensors_summary = []
        for sid, sensor in self._sensors.items():
            stype = sensor.get("type", "")
            state = sensor.get("state", {})
            if stype == "ZLLPresence":
                # Find associated light level and temperature sensors (same uniqueid prefix)
                uid_prefix = sensor.get("uniqueid", "")[:23]  # MAC + endpoint prefix
                light_level = None
                temperature = None
                for s2id, s2 in self._sensors.items():
                    if s2.get("uniqueid", "")[:23] == uid_prefix and s2id != sid:
                        if s2.get("type") == "ZLLLightLevel":
                            light_level = s2.get("state", {}).get("lightlevel")
                        elif s2.get("type") == "ZLLTemperature":
                            raw = s2.get("state", {}).get("temperature")
                            temperature = round(raw / 100, 1) if raw is not None else None
                sensors_summary.append({
                    "id": sid,
                    "name": sensor.get("name", f"Sensor {sid}"),
                    "presence": state.get("presence", False),
                    "last_updated": state.get("lastupdated", ""),
                    "light_level": light_level,
                    "temperature": temperature,
                    "battery": sensor.get("config", {}).get("battery"),
                })
        return {
            "bridge_ip": self._bridge_ip,
            "bridge_name": self._bridge_name,
            "auth_state": self._auth_state,
            "auth_message": self._auth_message,
            "light_count": len(self._lights),
            "lights": lights_summary,
            "sensors": sensors_summary,
        }

    # ── Powers ──────────────────────────────────────────────────────

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="discover_bridge",
                type=PowerType.MCP,
                description="Discover Philips Hue Bridge on the local network",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="pair_bridge",
                type=PowerType.MCP,
                description="Pair with Hue Bridge (press the link button first, then call this)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "bridge_ip": {
                            "type": "string",
                            "description": "Bridge IP address (auto-discovered if omitted)",
                        },
                    },
                },
            ),
            Power(
                name="set_api_key",
                type=PowerType.MCP,
                description="Manually set the Hue API key (for users who already have one)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "bridge_ip": {
                            "type": "string",
                            "description": "Bridge IP address",
                        },
                        "api_key": {
                            "type": "string",
                            "description": "Hue API username/key",
                        },
                    },
                    "required": ["bridge_ip", "api_key"],
                },
            ),
            Power(
                name="get_lights",
                type=PowerType.MCP,
                description="List all lights with their current state",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="set_light",
                type=PowerType.MCP,
                description="Control a light (on/off, brightness, color)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "light_id": {"type": "string", "description": "Light ID"},
                        "on": {"type": "boolean", "description": "Turn on/off"},
                        "brightness": {
                            "type": "integer", "minimum": 1, "maximum": 254,
                            "description": "Brightness (1-254)",
                        },
                        "color_temp": {
                            "type": "integer", "minimum": 153, "maximum": 500,
                            "description": "Color temperature in mirek (153=cold, 500=warm)",
                        },
                        "hue": {
                            "type": "integer", "minimum": 0, "maximum": 65535,
                            "description": "Hue (0-65535, red=0, green=25500, blue=46920)",
                        },
                        "saturation": {
                            "type": "integer", "minimum": 0, "maximum": 254,
                            "description": "Saturation (0-254)",
                        },
                    },
                    "required": ["light_id"],
                },
            ),
            Power(
                name="get_groups",
                type=PowerType.MCP,
                description="List all rooms/groups with their lights",
                input_schema={"type": "object", "properties": {}},
            ),
            Power(
                name="set_group",
                type=PowerType.MCP,
                description="Control all lights in a group/room",
                input_schema={
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "string", "description": "Group ID"},
                        "on": {"type": "boolean", "description": "Turn all on/off"},
                        "brightness": {
                            "type": "integer", "minimum": 1, "maximum": 254,
                            "description": "Brightness (1-254)",
                        },
                        "scene": {"type": "string", "description": "Scene ID to activate"},
                    },
                    "required": ["group_id"],
                },
            ),
            Power(
                name="get_sensors",
                type=PowerType.MCP,
                description="List all motion sensors with presence, temperature, and light level",
                input_schema={"type": "object", "properties": {}},
            ),
            # Connector commands
            Power(name="lights", type=PowerType.COMMAND, description="List lights"),
            Power(name="rooms", type=PowerType.COMMAND, description="List rooms"),
            Power(name="sensors", type=PowerType.COMMAND, description="List motion sensors"),
        ]

    def _discover_all_bridges(self) -> list[dict[str, str]]:
        """Find all bridges via cloud discovery, mDNS, or known IP."""
        bridges: list[dict[str, str]] = []
        seen_ips: set[str] = set()

        # Method 1: Hue cloud discovery
        try:
            data = json.loads(urlopen(_DISCOVER_URL, timeout=5).read())
            if isinstance(data, list):
                for entry in data:
                    ip = entry.get("internalipaddress")
                    if ip and ip not in seen_ips:
                        seen_ips.add(ip)
                        name = "Hue Bridge"
                        try:
                            cfg = _hue_get(f"https://{ip}/api/0/config", timeout=2)
                            name = cfg.get("name", name)
                        except Exception:
                            pass
                        bridges.append({"ip": ip, "name": name, "id": entry.get("id", "")})
        except Exception:
            pass

        # Method 2: mDNS via dns-sd (macOS)
        if not bridges:
            try:
                import subprocess
                proc = subprocess.run(
                    ["dns-sd", "-B", "_hue._tcp", "local."],
                    capture_output=True, text=True, timeout=4,
                )
                # Parse instance names, then resolve IPs
                for line in proc.stdout.splitlines():
                    if "Hue Bridge" in line:
                        # Resolve the bridge IP via config endpoint on common subnet
                        break
            except Exception:
                pass

        # Method 3: Parallel subnet scan for Hue bridges
        if not bridges:
            import socket
            from concurrent.futures import ThreadPoolExecutor
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                prefix = ".".join(local_ip.split(".")[:3])

                def _probe(ip: str) -> dict[str, str] | None:
                    try:
                        cfg = _hue_get(f"https://{ip}/api/0/config", timeout=0.5)
                        if "bridgeid" in cfg:
                            return {"ip": ip, "name": cfg.get("name", "Hue Bridge"),
                                    "id": cfg.get("bridgeid", "")}
                    except Exception:
                        pass
                    return None

                candidates = [f"{prefix}.{i}" for i in range(1, 255)
                              if f"{prefix}.{i}" not in seen_ips]
                with ThreadPoolExecutor(max_workers=50) as pool:
                    for result in pool.map(_probe, candidates):
                        if result:
                            seen_ips.add(result["ip"])
                            bridges.append(result)
            except Exception:
                pass

        # Fallback: try stored IP
        if not bridges and self._bridge_ip:
            try:
                cfg = _hue_get(f"https://{self._bridge_ip}/api/0/config", timeout=2)
                bridges.append({
                    "ip": self._bridge_ip,
                    "name": cfg.get("name", "Hue Bridge"),
                    "id": cfg.get("bridgeid", ""),
                })
            except Exception:
                bridges.append({"ip": self._bridge_ip, "name": "Hue Bridge", "id": ""})

        return bridges

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        # ── Discovery ──
        if name == "discover_bridge":
            bridges = self._discover_all_bridges()
            if bridges:
                self._bridge_ip = bridges[0]["ip"]
                # Check if we already have a stored key
                if await self._load_stored_key():
                    self.poll_lights()
                    return {"content": [{"type": "text", "text": f"Authenticated with {self._bridge_ip}"}],
                            "bridges": bridges, "authenticated": True}
                return {"content": [{"type": "text", "text": f"Found {len(bridges)} bridge(s)"}],
                        "bridges": bridges, "authenticated": False}
            return _mcp_text("No Hue Bridge found on the network.", error=True)

        # ── Pairing ──
        if name == "pair_bridge":
            ip = args.get("bridge_ip") or self._bridge_ip
            if not ip:
                ip = self._discover_bridge()
            if not ip:
                return _mcp_text("No bridge IP. Run discover_bridge first.", error=True)
            self._bridge_ip = ip
            self._auth_state = "pairing"
            key = self._try_pair(ip)
            if key:
                self._api_key = key
                self._auth_state = "ok"
                await self._save_key(ip, key)
                self.poll_lights()
                return _mcp_text(f"Paired with bridge at {ip}. {len(self._lights)} lights found.")
            return _mcp_text(
                "Link button not pressed. Press the button on the Hue Bridge and try again within 30 seconds.",
                error=True,
            )

        # ── Manual key ──
        if name == "set_api_key":
            ip = args["bridge_ip"]
            key = args["api_key"]
            self._bridge_ip = ip
            self._api_key = key
            await self._save_key(ip, key)
            self.poll_lights()
            if self._auth_state == "ok":
                return _mcp_text(f"API key set. Connected to bridge at {ip}. {len(self._lights)} lights found.")
            return _mcp_text(f"API key set but connection failed: {self._auth_message}", error=True)

        # ── Lights ──
        if name == "get_lights" or name == "lights":
            if not self._api_key:
                return _mcp_text("Not connected. Run discover_bridge and pair_bridge first.", error=True)
            if not self._lights:
                self.poll_lights()
            lines = []
            for lid, light in self._lights.items():
                s = light.get("state", {})
                status = "ON" if s.get("on") else "OFF"
                bri = s.get("bri", 0)
                reach = "reachable" if s.get("reachable") else "unreachable"
                lines.append(f"  [{lid}] {light.get('name', '?')}: {status} bri={bri} ({reach})")
            text = f"Lights ({len(self._lights)}):\n" + "\n".join(lines) if lines else "No lights found."
            if name == "lights":
                return text
            return _mcp_text(text)

        # ── Set light ──
        if name == "set_light":
            if not self._api_key:
                return _mcp_text("Not connected.", error=True)
            lid = args["light_id"]
            body: dict[str, Any] = {}
            if "on" in args:
                body["on"] = args["on"]
            if "brightness" in args:
                body["bri"] = args["brightness"]
            if "color_temp" in args:
                body["ct"] = args["color_temp"]
            if "hue" in args:
                body["hue"] = args["hue"]
            if "saturation" in args:
                body["sat"] = args["saturation"]
            if not body:
                return _mcp_text("No state changes specified.", error=True)
            try:
                url = f"https://{self._bridge_ip}/api/{self._api_key}/lights/{lid}/state"
                data = json.dumps(body).encode()
                req = Request(url, data=data, method="PUT",
                              headers={"Content-Type": "application/json"})
                with urlopen(req, context=_SSL_CTX, timeout=5) as resp:
                    result = json.loads(resp.read())
                return _mcp_text(f"Light {lid} updated: {json.dumps(body)}")
            except Exception as e:
                return _mcp_text(f"Failed to set light: {e}", error=True)

        # ── Groups ──
        if name == "get_groups" or name == "rooms":
            if not self._api_key:
                return _mcp_text("Not connected.", error=True)
            if not self._groups:
                self.poll_lights()
            lines = []
            for gid, group in self._groups.items():
                status = "all on" if group.get("state", {}).get("all_on") else \
                         "some on" if group.get("state", {}).get("any_on") else "off"
                light_ids = group.get("lights", [])
                lines.append(f"  [{gid}] {group.get('name', '?')} ({group.get('type', '')}): "
                             f"{status}, {len(light_ids)} lights")
            text = f"Groups ({len(self._groups)}):\n" + "\n".join(lines) if lines else "No groups found."
            if name == "rooms":
                return text
            return _mcp_text(text)

        # ── Set group ──
        if name == "set_group":
            if not self._api_key:
                return _mcp_text("Not connected.", error=True)
            gid = args["group_id"]
            body: dict[str, Any] = {}
            if "on" in args:
                body["on"] = args["on"]
            if "brightness" in args:
                body["bri"] = args["brightness"]
            if "scene" in args:
                body["scene"] = args["scene"]
            if not body:
                return _mcp_text("No state changes specified.", error=True)
            try:
                url = f"https://{self._bridge_ip}/api/{self._api_key}/groups/{gid}/action"
                data = json.dumps(body).encode()
                req = Request(url, data=data, method="PUT",
                              headers={"Content-Type": "application/json"})
                with urlopen(req, context=_SSL_CTX, timeout=5) as resp:
                    result = json.loads(resp.read())
                return _mcp_text(f"Group {gid} updated: {json.dumps(body)}")
            except Exception as e:
                return _mcp_text(f"Failed to set group: {e}", error=True)

        # ── Sensors ──
        if name == "get_sensors" or name == "sensors":
            if not self._api_key:
                return _mcp_text("Not connected.", error=True)
            pulse = self.get_pulse()
            sensors = pulse.get("sensors", [])
            if not sensors:
                text = "No motion sensors found."
            else:
                lines = []
                for s in sensors:
                    parts = [f"  [{s['id']}] {s['name']}:"]
                    parts.append("MOTION" if s["presence"] else "clear")
                    if s["temperature"] is not None:
                        parts.append(f"{s['temperature']}\u00b0C")
                    if s["light_level"] is not None:
                        parts.append(f"lux={s['light_level']}")
                    if s.get("battery") is not None:
                        parts.append(f"bat={s['battery']}%")
                    lines.append(" ".join(parts))
                text = f"Sensors ({len(sensors)}):\n" + "\n".join(lines)
            if name == "sensors":
                return text
            return _mcp_text(text)

        return _mcp_text(f"Unknown power: {name}", error=True)


def _mcp_text(text: str, error: bool = False) -> dict[str, Any]:
    """Build an MCP text response."""
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if error:
        result["is_error"] = True
    return result
