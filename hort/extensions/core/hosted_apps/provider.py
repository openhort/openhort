"""Hosted Apps plugin — run isolated web apps as Docker containers.

Each instance is a Docker container on an isolated network. openhort
reverse-proxies HTTP/WebSocket to the container. Data persists in
named Docker volumes.

Security: same 7-layer model as Claude sandbox containers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any

from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin

# Lazy import to avoid relative import issues with plugin loader
def _load_catalog():  # type: ignore[no-untyped-def]
    import importlib.util
    import sys
    from pathlib import Path

    mod_name = "hort.extensions.core.hosted_apps.catalog"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    module_file = Path(__file__).parent / "catalog.py"
    spec = importlib.util.spec_from_file_location(mod_name, module_file)
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod
    raise ImportError("Failed to load catalog module")


# Will be initialized on first use
CATALOG: dict[str, Any] = {}
AppTemplate: Any = None


def _ensure_catalog() -> None:
    global CATALOG, AppTemplate  # noqa: PLW0603
    if not CATALOG:
        mod = _load_catalog()
        CATALOG = mod.CATALOG
        AppTemplate = mod.AppTemplate


def get_catalog() -> dict[str, Any]:
    _ensure_catalog()
    mod = _load_catalog()
    return mod.get_catalog()

logger = logging.getLogger(__name__)

CONTAINER_PREFIX = "ohapp-"
VOLUME_PREFIX = "ohapp-data-"
NETWORK_NAME = "openhort-apps"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a docker CLI command."""
    cmd = ["docker", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=120)


def _docker_output(*args: str) -> str:
    """Run docker command and return stdout."""
    result = _docker(*args, check=False)
    return result.stdout.strip()


class HostedAppsPlugin(PluginBase, ScheduledMixin, MCPMixin):
    """Manages Docker containers for hosted web apps."""

    _instances: dict[str, dict[str, Any]]

    def activate(self, config: dict[str, Any]) -> None:
        _ensure_catalog()
        self._instances = {}
        self._network = config.get("network_name", NETWORK_NAME)

        # Check Docker availability
        try:
            _docker("version")
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.log.warning("Docker not available — hosted-apps disabled")
            return

        self._ensure_network()
        self._discover_running()
        self.log.info(
            "hosted-apps activated: %d running instances",
            len(self._instances),
        )

    def deactivate(self) -> None:
        self.log.info("hosted-apps deactivated (%d instances)", len(self._instances))

    # ===== Docker Operations =====

    def _ensure_network(self) -> None:
        """Create the isolated Docker network if it doesn't exist."""
        existing = _docker_output("network", "ls", "--filter", f"name={self._network}", "--format", "{{.Name}}")
        if self._network not in existing.split("\n"):
            _docker("network", "create", "--driver", "bridge", self._network)
            self.log.info("created isolated network: %s", self._network)

            # Connect openhort host to the network so it can reach containers
            # Find our own container (if running in Docker) or connect the host
            try:
                _docker("network", "connect", self._network, "host", check=False)
            except Exception:
                pass

    def _discover_running(self) -> None:
        """Discover existing containers with our prefix."""
        output = _docker_output(
            "ps", "-a",
            "--filter", f"name={CONTAINER_PREFIX}",
            "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}",
        )
        if not output:
            return
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            name, status, image = parts[0], parts[1], parts[2]
            instance_name = name.replace(CONTAINER_PREFIX, "")
            # Find app type from image
            app_type = self._image_to_type(image)
            template = CATALOG.get(app_type)
            self._instances[instance_name] = {
                "name": instance_name,
                "type": app_type,
                "container": name,
                "image": image,
                "port": template.port if template else 0,
                "status": "running" if "Up" in status else "stopped",
            }
            self.log.info("discovered instance: %s (%s, %s)", instance_name, app_type, status)

    def _image_to_type(self, image: str) -> str:
        """Map a Docker image name to an app type."""
        for app_type, template in CATALOG.items():
            if template.image.split(":")[0] in image:
                return app_type
        return "unknown"

    def create_instance(self, app_type: str, name: str) -> dict[str, Any]:
        """Create and start a new app instance."""
        if app_type not in CATALOG:
            raise ValueError(f"Unknown app type: {app_type}. Available: {list(CATALOG.keys())}")

        # Sanitize name
        safe_name = "".join(c for c in name.lower().replace(" ", "-") if c.isalnum() or c == "-")
        if not safe_name:
            safe_name = f"{app_type}-1"

        if safe_name in self._instances:
            raise ValueError(f"Instance '{safe_name}' already exists")

        template = CATALOG[app_type]
        container_name = f"{CONTAINER_PREFIX}{safe_name}"
        volume_name = f"{VOLUME_PREFIX}{safe_name}"

        # Create persistent volume
        _docker("volume", "create", volume_name)

        # Build docker create command
        args = [
            "create",
            "--name", container_name,
            "--network", self._network,
            "--cap-drop", "ALL",
            "--cap-add", "NET_BIND_SERVICE",
            "--cap-add", "CHOWN",
            "--cap-add", "SETUID",
            "--cap-add", "SETGID",
            "--security-opt", "no-new-privileges:true",
            "--memory", template.memory,
            "--cpus", template.cpus,
            "--pids-limit", "256",
            "-v", f"{volume_name}:{template.data_path}",
            "--restart", "unless-stopped",
            "-p", f"127.0.0.1:0:{template.port}",  # Bind to localhost only, random host port
        ]

        # User override (some images require root internally)
        if template.user:
            args.extend(["--user", template.user])

        # Environment variables
        for k, v in template.env.items():
            args.extend(["-e", f"{k}={v}"])

        # Set base URL/path prefix for apps that support it
        proxy_prefix = f"/app/{safe_name}/~"
        # No path prefix on the container — the proxy handles path rewriting.
        # N8N_PATH doesn't work for API routes, only frontend.

        # Image
        args.append(template.image)

        # Extra args (e.g., command-line flags for the app)
        args.extend(template.extra_args)

        _docker(*args)
        _docker("start", container_name)

        # Auto-setup for apps that need initial configuration
        if template.app_type == "n8n":
            self._auto_setup_n8n(container_name, template.port)

        instance = {
            "name": safe_name,
            "type": app_type,
            "container": container_name,
            "image": template.image,
            "port": template.port,
            "status": "running",
            "label": template.label,
            "icon": template.icon,
        }
        self._instances[safe_name] = instance

        self.log.info("created instance: %s (%s)", safe_name, app_type)
        return instance

    def stop_instance(self, name: str) -> bool:
        """Stop a running instance."""
        inst = self._instances.get(name)
        if not inst:
            return False
        _docker("stop", inst["container"], check=False)
        inst["status"] = "stopped"
        self.log.info("stopped instance: %s", name)
        return True

    def start_instance(self, name: str) -> bool:
        """Start a stopped instance."""
        inst = self._instances.get(name)
        if not inst:
            return False
        _docker("start", inst["container"], check=False)
        inst["status"] = "running"
        self.log.info("started instance: %s", name)
        return True

    def destroy_instance(self, name: str) -> bool:
        """Remove container and volume (data is deleted)."""
        inst = self._instances.get(name)
        if not inst:
            return False
        container = inst["container"]
        volume = f"{VOLUME_PREFIX}{name}"

        _docker("rm", "-f", container, check=False)
        _docker("volume", "rm", volume, check=False)

        del self._instances[name]
        self.log.info("destroyed instance: %s (volume %s removed)", name, volume)
        return True

    def list_instances(self) -> list[dict[str, Any]]:
        """List all instances with current status and mapped port."""
        result = []
        for inst in self._instances.values():
            entry = dict(inst)
            entry["host_port"] = self._get_host_port(inst["name"])
            result.append(entry)
        return result

    def get_container_url(self, name: str) -> str | None:
        """Get the localhost URL for an instance (via published port)."""
        inst = self._instances.get(name)
        if not inst or inst["status"] != "running":
            return None
        host_port = self._get_host_port(name)
        if host_port:
            return f"http://127.0.0.1:{host_port}"
        return None

    def _get_host_port(self, name: str) -> str | None:
        """Get the mapped host port for an instance."""
        inst = self._instances.get(name)
        if not inst:
            return None
        container = inst["container"]
        try:
            port_output = _docker_output("port", container, str(inst["port"]))
            if port_output:
                return port_output.strip().split(":")[-1]
        except Exception:
            pass
        return None

    def get_instance_info(self, name: str) -> dict[str, Any] | None:
        """Get full instance info including mapped port for iframe."""
        inst = self._instances.get(name)
        if not inst:
            return None
        host_port = self._get_host_port(name)
        return {**inst, "host_port": host_port}

    # ===== Auto-setup =====

    def _auto_setup_n8n(self, container_name: str, port: int) -> None:
        """Wait for n8n to start and create the owner account automatically."""
        import time
        import urllib.request

        # Get mapped host port
        port_output = _docker_output("port", container_name, str(port))
        if not port_output:
            return
        host_port = port_output.strip().split(":")[-1]
        base = f"http://127.0.0.1:{host_port}"

        # Wait for n8n to be ready (up to 30s)
        for _ in range(30):
            try:
                req = urllib.request.Request(f"{base}/rest/settings")
                urllib.request.urlopen(req, timeout=2)
                break
            except Exception:
                time.sleep(1)
        else:
            self.log.warning("n8n didn't start in 30s — skipping auto-setup")
            return

        # Create owner
        try:
            data = json.dumps({
                "email": "admin@openhort.local",
                "firstName": "Admin",
                "lastName": "User",
                "password": "OpenHort2026!",
            }).encode()
            req = urllib.request.Request(
                f"{base}/rest/owner/setup",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            self.log.info("n8n owner account created automatically")
        except Exception as exc:
            self.log.debug("n8n auto-setup: %s (may already be set up)", exc)

    # ===== Scheduler =====

    def poll_instances(self) -> None:
        """Update instance status from Docker. Runs in executor thread."""
        try:
            output = _docker_output(
                "ps", "-a",
                "--filter", f"name={CONTAINER_PREFIX}",
                "--format", "{{.Names}}\t{{.Status}}",
            )
            running = {}
            for line in (output or "").strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    name = parts[0].replace(CONTAINER_PREFIX, "")
                    running[name] = "running" if "Up" in parts[1] else "stopped"

            for name, inst in self._instances.items():
                inst["status"] = running.get(name, "stopped")
        except Exception as exc:
            self.log.debug("poll failed: %s", exc)

    # ===== Status for thumbnail =====

    def get_status(self) -> dict[str, Any]:
        running = sum(1 for i in self._instances.values() if i.get("status") == "running")
        return {
            "total": len(self._instances),
            "running": running,
            "instances": [
                {
                    "name": i["name"],
                    "type": i.get("type", ""),
                    "status": i.get("status", ""),
                    "label": CATALOG.get(i.get("type", ""), AppTemplate("", "", "", "", 0, "", "")).label or i.get("type", ""),
                    "icon": CATALOG.get(i.get("type", ""), AppTemplate("", "", "", "", 0, "", "")).icon or "",
                }
                for i in self._instances.values()
            ],
        }

    # ===== MCP Tools =====

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="hosted_apps_catalog",
                description="List available app types that can be installed",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="hosted_apps_create",
                description="Create a new hosted app instance (e.g., n8n, code-server, jupyter)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "app_type": {"type": "string", "description": "App type from catalog"},
                        "name": {"type": "string", "description": "Instance name"},
                    },
                    "required": ["app_type"],
                },
            ),
            MCPToolDef(
                name="hosted_apps_list",
                description="List all hosted app instances with status",
                input_schema={"type": "object", "properties": {}},
            ),
            MCPToolDef(
                name="hosted_apps_stop",
                description="Stop a running hosted app instance",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            MCPToolDef(
                name="hosted_apps_start",
                description="Start a stopped hosted app instance",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            MCPToolDef(
                name="hosted_apps_destroy",
                description="Destroy a hosted app instance and its data",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
        ]

    async def execute_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolResult:
        if tool_name == "hosted_apps_catalog":
            return MCPToolResult(content=[{"type": "text", "text": json.dumps(get_catalog(), indent=2)}])

        if tool_name == "hosted_apps_create":
            app_type = arguments.get("app_type", "")
            name = arguments.get("name", app_type)
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.create_instance, app_type, name
                )
                return MCPToolResult(content=[{"type": "text", "text": f"Created: {result['name']} ({result['type']})\nURL: /app/{result['name']}/"}])
            except Exception as exc:
                return MCPToolResult(content=[{"type": "text", "text": f"Error: {exc}"}], is_error=True)

        if tool_name == "hosted_apps_list":
            instances = self.list_instances()
            if not instances:
                return MCPToolResult(content=[{"type": "text", "text": "No instances"}])
            lines = [f"{i['name']} ({i.get('type','')}) — {i.get('status','')}" for i in instances]
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])

        if tool_name == "hosted_apps_stop":
            ok = await asyncio.get_event_loop().run_in_executor(None, self.stop_instance, arguments["name"])
            return MCPToolResult(content=[{"type": "text", "text": "Stopped" if ok else "Not found"}])

        if tool_name == "hosted_apps_start":
            ok = await asyncio.get_event_loop().run_in_executor(None, self.start_instance, arguments["name"])
            return MCPToolResult(content=[{"type": "text", "text": "Started" if ok else "Not found"}])

        if tool_name == "hosted_apps_destroy":
            ok = await asyncio.get_event_loop().run_in_executor(None, self.destroy_instance, arguments["name"])
            return MCPToolResult(content=[{"type": "text", "text": "Destroyed" if ok else "Not found"}])

        return MCPToolResult(content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}], is_error=True)
