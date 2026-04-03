# Container Environments

openhort can manage isolated container environments for running and testing applications. Containers run locally (Docker) or in the cloud (Azure Container Instances), with a unified interface for both.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  openhort server                                    │
│                                                     │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │ ContainerMgr │    │ hort/containers/           │  │
│  │   (ABC)      │    │   base.py    — interface   │  │
│  │              │    │   docker.py  — Docker impl │  │
│  │ .create()    │    │   azure.py   — ACI impl    │  │
│  │ .start()     │    │   models.py  — data types  │  │
│  │ .stop()      │    │   registry.py— tracking    │  │
│  │ .exec()      │    └───────────────────────────┘  │
│  │ .get_url()   │                                   │
│  │ .destroy()   │    ┌───────────────────────────┐  │
│  └──────┬───────┘    │ Preview panel (extension)  │  │
│         │            │ iframe in openhort UI      │  │
│         │            └───────────────────────────┘  │
│         │                                           │
└─────────┼───────────────────────────────────────────┘
          │
    ┌─────┴──────┐          ┌──────────────┐
    │   Docker   │          │  Azure ACI   │
    │ (local)    │          │  (cloud)     │
    │ port fwd   │          │  public IP   │
    └────────────┘          └──────────────┘
```

## Provider Interface

All container providers implement `ContainerProvider` — a single ABC that manages the full lifecycle:

```python
from hort.containers.base import ContainerProvider, ContainerInfo, ExecResult

class ContainerProvider(ABC):
    """Manages container lifecycle on a specific platform."""

    @abstractmethod
    async def create(self, config: ContainerConfig) -> ContainerInfo: ...

    @abstractmethod
    async def start(self, container_id: str) -> bool: ...

    @abstractmethod
    async def stop(self, container_id: str) -> bool: ...

    @abstractmethod
    async def destroy(self, container_id: str) -> bool: ...

    @abstractmethod
    async def exec(self, container_id: str, command: str,
                   timeout: float = 30.0) -> ExecResult: ...

    @abstractmethod
    async def get_info(self, container_id: str) -> ContainerInfo | None: ...

    @abstractmethod
    async def list_containers(self) -> list[ContainerInfo]: ...

    @abstractmethod
    async def get_url(self, container_id: str, container_port: int) -> str | None: ...
```

## Data Models

```python
@dataclass(frozen=True)
class ContainerConfig:
    """Configuration for creating a container."""
    name: str                           # Human-readable name
    image: str                          # Docker image (e.g. "python:3.12-slim")
    command: str | None = None          # Override entrypoint
    ports: dict[int, int] = {}          # container_port → host_port
    env: dict[str, str] = {}            # Environment variables
    mounts: list[MountConfig] = []      # Volume mounts
    working_dir: str = "/app"
    memory_mb: int = 512
    cpu_count: float = 1.0

@dataclass(frozen=True)
class MountConfig:
    """A volume or bind mount."""
    host_path: str                      # Host path or volume name
    container_path: str                 # Path inside container
    read_only: bool = False

@dataclass(frozen=True)
class ContainerInfo:
    """Runtime state of a container."""
    container_id: str
    name: str
    status: str                         # "created", "running", "stopped", "destroyed"
    image: str
    ports: dict[int, int]               # container_port → mapped_port
    provider: str                       # "docker" or "azure"
    url: str | None = None              # Base URL if accessible

@dataclass(frozen=True)
class ExecResult:
    """Result of executing a command in a container."""
    exit_code: int
    stdout: str
    stderr: str
```

## Docker Provider

Uses the Docker CLI (no Docker SDK dependency — keeps things simple and compatible with IsoClaude patterns).

```python
class DockerProvider(ContainerProvider):
    """Local Docker container management."""

    async def create(self, config: ContainerConfig) -> ContainerInfo:
        # docker create --name {name} -p {ports} -v {mounts} -e {env} {image}
        ...

    async def exec(self, container_id: str, command: str, ...) -> ExecResult:
        # docker exec {container_id} sh -c {command}
        ...

    async def get_url(self, container_id: str, container_port: int) -> str | None:
        # Returns http://localhost:{mapped_port}
        ...
```

### Port Mapping Strategy

Follows IsoClaude's convention for predictable port mapping:

| Container Port | Host Port | Description |
|---|---|---|
| 3000 | 3000 | Desktop (noVNC) |
| 8000-8999 | 9000-9999 | Application ports |
| 22 | 2222 | SSH |

Example: A FastAPI app on port 8000 inside the container → accessible at `http://localhost:9000`.

### IsoClaude Compatibility

The Docker provider can manage IsoClaude-style containers:
- Uses the same webtop image and volume layout
- Reads `projects.conf` to discover existing IsoClaude environments
- Can attach to running IsoClaude containers for exec/preview

## Azure Provider

Uses the `az` CLI for Azure Container Instances.

```python
class AzureProvider(ContainerProvider):
    """Azure Container Instances management."""

    def __init__(self, resource_group: str, registry: str | None = None):
        self._rg = resource_group
        self._registry = registry  # ACR for private images

    async def create(self, config: ContainerConfig) -> ContainerInfo:
        # az container create --resource-group {rg} --name {name}
        #   --image {image} --ports {ports} --cpu {cpu} --memory {mem}
        ...

    async def exec(self, container_id: str, command: str, ...) -> ExecResult:
        # az container exec --resource-group {rg} --name {name}
        #   --exec-command {command}
        ...

    async def get_url(self, container_id: str, container_port: int) -> str | None:
        # Returns http://{public_ip}:{port}
        ...
```

### Key Differences from Docker

| Aspect | Docker | Azure ACI |
|---|---|---|
| Port mapping | localhost:host_port | public_ip:container_port |
| Volumes | Bind mounts, named volumes | Azure File Share (SMB) |
| Exec | `docker exec` (instant) | `az container exec` (REST API) |
| Images | Local or Docker Hub | ACR, Docker Hub, any registry |
| Cost | Free (local CPU) | Per-second billing |
| Startup time | ~1s | ~30-60s |
| Networking | Port forwarding | Public IP or VNet |

### Volume Mapping

Docker bind mounts don't exist in Azure. The provider translates:

```python
# Docker: mount host directory
MountConfig(host_path="/Users/me/project", container_path="/app")

# Azure: upload to File Share, mount share
# Provider handles the translation transparently
```

## Container Registry (Tracking)

`ContainerRegistry` tracks all active containers across providers:

```python
class ContainerRegistry:
    """Tracks containers across all providers."""

    def register(self, info: ContainerInfo) -> None: ...
    def get(self, container_id: str) -> ContainerInfo | None: ...
    def list_all(self) -> list[ContainerInfo]: ...
    def remove(self, container_id: str) -> None: ...
    def get_provider(self, container_id: str) -> ContainerProvider | None: ...
```

## Control WebSocket Integration

Container operations are exposed as control WS messages:

```
→ {"type": "container_create", "provider": "docker", "config": {...}}
← {"type": "container_created", "container": {...}}

→ {"type": "container_exec", "container_id": "abc123", "command": "python -m pytest"}
← {"type": "container_exec_result", "exit_code": 0, "stdout": "...", "stderr": "..."}

→ {"type": "container_list"}
← {"type": "container_list", "containers": [...]}

→ {"type": "container_preview", "container_id": "abc123", "port": 8000}
← {"type": "container_preview_url", "url": "http://localhost:9000"}

→ {"type": "container_stop", "container_id": "abc123"}
← {"type": "container_stopped", "ok": true}

→ {"type": "container_destroy", "container_id": "abc123"}
← {"type": "container_destroyed", "ok": true}
```

## Preview Panel (UI Extension)

The preview extension adds an iframe panel to the openhort viewer:

```javascript
class PreviewPanel extends HortExtension {
    static id = 'preview';
    static name = 'Preview';

    setup(app, Quasar) {
        app.component('preview-panel', {
            template: `
                <div v-if="url" class="preview-panel">
                    <iframe :src="url" frameborder="0"></iframe>
                </div>
            `,
            // ...
        });
    }
}
```

The preview URL comes from `container.get_url(container_id, port)`:
- Docker: `http://localhost:9000` (port-forwarded)
- Azure: `http://<public-ip>:8000` (direct)

## Playwright Verification

Claude uses Playwright to verify the running app:

```python
# In Claude's workflow:
container = await provider.create(ContainerConfig(
    name="my-app",
    image="python:3.12-slim",
    ports={8000: 9000},
    mounts=[MountConfig("/path/to/project", "/app")],
))
await provider.start(container.container_id)
await provider.exec(container.container_id, "pip install -r requirements.txt")
await provider.exec(container.container_id, "python -m uvicorn app:app --host 0.0.0.0 --port 8000 &")

# Verify with Playwright
url = await provider.get_url(container.container_id, 8000)
page = await browser.new_page()
await page.goto(url)
await page.screenshot(path="preview.png")

# User sees it live in openhort via the preview panel or window stream
```

## Configuration

```toml
# In a future hort config file
[containers]
default_provider = "docker"

[containers.docker]
port_offset = 1000          # container 8xxx → host 9xxx

[containers.azure]
resource_group = "openhort-rg"
registry = "openhortacr.azurecr.io"
location = "westeurope"
```

## Directory Layout

```
hort/
  containers/
    __init__.py
    base.py          # ContainerProvider ABC, data models
    docker.py        # DockerProvider implementation
    azure.py         # AzureProvider implementation (future)
    registry.py      # ContainerRegistry (tracking)
```

## Relationship to IsoClaude

IsoClaude is a standalone bash tool for creating full desktop environments. The openhort container system is complementary:

| | IsoClaude | openhort containers |
|---|---|---|
| Purpose | Full dev environment | Run & test apps |
| Complexity | KDE desktop, SSH, VS Code | Lightweight app containers |
| Interaction | Terminal / noVNC / SSH | Control WS + preview panel |
| Config | projects.conf (TOML) | ContainerConfig (Python) |
| Lifecycle | Long-running | Ephemeral or long-running |

The Docker provider can discover and attach to IsoClaude containers for exec and preview, making them interoperable.
