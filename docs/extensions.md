# Extension System

## Overview

The openhort extension system makes every platform-specific capability replaceable and composable. The server never imports macOS, Windows, or Linux code directly — it asks the extension registry for a **provider** that satisfies an abstract interface.

**Design goals:**

1. **Cross-platform** — the core package installs on macOS, Linux, and Windows. Platform-specific code lives in extensions.
2. **Replaceable** — any capability (window listing, screen capture, input simulation, workspace management) can be swapped by loading a different extension.
3. **Composable** — an extension can provide one capability or many. A single macOS extension provides all four platform capabilities; a Docker extension might only provide `command.target`.
4. **Configurable** — user configuration selects which extension provides each capability, and each extension accepts its own config.
5. **Future-proof** — extensions will eventually be fetched dynamically from an external repository.

## Directory Layout

```
hort/extensions/                    # Built-in extensions (shipped with the package)
  core/
    <extension_name>/
      extension.json                # Manifest
      __init__.py                   # Python package marker
      provider.py                   # Entry point module
      static/                       # Optional client-side assets

~/.hort/extensions/                 # Third-party extensions (future, separate repo)
  <provider>/
    <extension_name>/
      extension.json
      provider.py
```

The `provider` directory is a namespace that identifies who maintains the extension. Built-in extensions use `core`. Third-party extensions use their org name or handle.

**Current layout:**

```
hort/extensions/
  core/
    macos_windows/                  # macOS window management (Quartz + SkyLight)
      extension.json
      __init__.py
      provider.py
    linux_windows/                  # Linux via Docker (Xvfb + xdotool)
      extension.json
      __init__.py
      provider.py
      Dockerfile
      entrypoint.sh
```

## Manifest (`extension.json`)

Every extension must have an `extension.json` at its root. This is the only required file.

```json
{
  "name": "macos-windows",
  "version": "0.1.0",
  "description": "macOS window management via Quartz and SkyLight APIs",
  "provider": "core",
  "platforms": ["darwin"],
  "capabilities": [
    "window.list",
    "window.capture",
    "input.simulate",
    "workspace.manage"
  ],
  "python_dependencies": [
    "pyobjc-framework-Quartz>=11.0",
    "pyobjc-framework-ApplicationServices>=12.1"
  ],
  "entry_point": "provider:MacOSWindowsExtension",
  "config_schema": {
    "type": "object",
    "properties": {
      "exclude_apps": {
        "type": "array",
        "items": {"type": "string"},
        "default": []
      }
    }
  }
}
```

### Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `string` | **yes** | Unique extension identifier (kebab-case) |
| `version` | `string` | no | SemVer version (`"0.0.0"` default) |
| `description` | `string` | no | Human-readable description |
| `provider` | `string` | no | Namespace (`"core"` default) |
| `platforms` | `string[]` | no | Compatible `sys.platform` values. Default: all platforms |
| `capabilities` | `string[]` | no | List of capabilities this extension provides |
| `python_dependencies` | `string[]` | no | PEP 508 dependency strings |
| `entry_point` | `string` | no | `"module:ClassName"` — module file and class to instantiate |
| `config_schema` | `object` | no | JSON Schema for per-extension configuration |
| `path` | `string` | — | Set automatically during discovery (do not set manually) |

### Capability Strings

| Capability | Interface | Description |
|---|---|---|
| `window.list` | `WindowProvider` | List windows on a target |
| `window.capture` | `CaptureProvider` | Capture window screenshots |
| `input.simulate` | `InputProvider` | Simulate mouse/keyboard/scroll |
| `workspace.manage` | `WorkspaceProvider` | Manage virtual desktops/Spaces |
| `action` | `ActionProvider` | App-specific actions |
| `command.target` | `CommandTarget` | Execute shell commands on a target |
| `ui.panel` | `UIProvider` | Client-side UI components |

## Provider Interfaces

All interfaces are defined in `hort/ext/types.py`. Extensions implement one or more of these ABCs.

### `PlatformProvider` — Unified Platform Interface

The server uses this single interface for all platform operations. It combines window listing, screen capture, input simulation, and workspace management:

```python
class PlatformProvider(
    WindowProvider, CaptureProvider, InputProvider, WorkspaceProvider
):
    """Unified interface for a complete platform implementation.

    The server imports this one type and calls its methods without
    knowing whether it's talking to macOS, Windows, or Linux.
    """
```

A platform extension (like `macos-windows`) implements `PlatformProvider` to supply all four capabilities at once. The server retrieves it as:

```python
platform = registry.get_provider("window.list", PlatformProvider)
# Now use platform.list_windows(), platform.capture_window(), etc.
```

### `WindowProvider`

```python
class WindowProvider(ABC):
    @abstractmethod
    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]: ...

    def get_app_names(self) -> list[str]:
        """Default: extract sorted unique names from list_windows()."""
```

### `CaptureProvider`

```python
class CaptureProvider(ABC):
    @abstractmethod
    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None: ...
```

Returns JPEG bytes or `None` on failure.

### `InputProvider`

```python
class InputProvider(ABC):
    @abstractmethod
    def handle_input(
        self, event: InputEvent, bounds: WindowBounds, pid: int = 0
    ) -> None: ...

    @abstractmethod
    def activate_app(
        self, pid: int, bounds: WindowBounds | None = None
    ) -> None: ...
```

### `WorkspaceProvider`

```python
class WorkspaceProvider(ABC):
    @abstractmethod
    def get_workspaces(self) -> list[WorkspaceInfo]: ...

    def get_current_index(self) -> int:
        """Default: find first workspace where is_current=True."""

    @abstractmethod
    def switch_to(self, target_index: int) -> bool: ...
```

### `ActionProvider`

For app-specific operations — reload a Chrome tab, open a Windsurf project, run a build command:

```python
class ActionProvider(ABC):
    @abstractmethod
    def get_actions(self) -> list[ActionInfo]: ...

    @abstractmethod
    def execute(
        self, action_id: str, params: dict[str, Any] | None = None
    ) -> ActionResult: ...
```

### `CommandTarget`

For executing shell commands on local machines, containers, or remote VMs:

```python
class CommandTarget(ABC):
    @property
    @abstractmethod
    def target_name(self) -> str: ...

    @abstractmethod
    async def execute_command(
        self, command: str, timeout: float = 30.0
    ) -> CommandResult: ...

    @abstractmethod
    async def is_available(self) -> bool: ...
```

### `UIProvider`

For extensions that add client-side UI panels or API routes:

```python
class UIProvider(ABC):
    def get_static_dir(self) -> Path | None: ...
    def get_routes(self) -> list[Any]: ...
```

## Configuration

### Extension Resolution

When multiple extensions provide the same capability, the **first loaded compatible extension wins**. Loading order follows filesystem sort order (provider name, then extension name).

Override via config to select a specific extension per capability:

```json
{
  "extensions": {
    "config": {
      "macos-windows": {
        "exclude_apps": ["SystemUIServer"]
      }
    }
  }
}
```

### Per-Extension Config

Each extension declares a `config_schema` (JSON Schema) in its manifest. The config is passed to the extension's `activate(config)` method during loading.

## Extension Lifecycle

```
1. DISCOVER   registry.discover(extensions_dir)
               └─ Scan extensions/<provider>/<name>/extension.json
               └─ Parse manifests, store internally

2. LOAD       registry.load_compatible(config)
               └─ Filter by sys.platform ∈ manifest.platforms
               └─ For each compatible extension:
                  └─ Import module from entry_point
                  └─ Instantiate class
                  └─ Call activate(config) if config provided
                  └─ Register capabilities in capability map

3. RESOLVE    registry.get_provider("window.list", WindowProvider)
               └─ Look up capability → extension name
               └─ Return instance if it matches the requested type
```

### Registry API

```python
from hort.ext import ExtensionRegistry, PlatformProvider

registry = ExtensionRegistry()
registry.discover(Path("extensions"))
registry.load_compatible(config={"macos-windows": {"exclude_apps": []}})

# Get a provider by capability
platform = registry.get_provider("window.list", PlatformProvider)
windows = platform.list_windows()
frame = platform.capture_window(windows[0].window_id)
```

## Creating an Extension

The following examples illustrate how to create different types of extensions. Only `core/macos-windows` is currently implemented — these serve as templates.

### Minimal Example: Null Platform (testing/CI)

```
extensions/core/null_platform/
  extension.json
  provider.py
```

**extension.json:**
```json
{
  "name": "null-platform",
  "version": "0.1.0",
  "description": "No-op platform for testing and CI",
  "provider": "core",
  "platforms": ["darwin", "linux", "win32"],
  "capabilities": ["window.list", "window.capture", "input.simulate", "workspace.manage"],
  "entry_point": "provider:NullPlatform"
}
```

**provider.py:**
```python
from hort.ext.types import PlatformProvider, WorkspaceInfo
from hort.models import InputEvent, WindowBounds, WindowInfo

class NullPlatform(PlatformProvider):
    def list_windows(self, app_filter=None):
        return []

    def capture_window(self, window_id, max_width=800, quality=70):
        return None

    def handle_input(self, event, bounds, pid=0):
        pass

    def activate_app(self, pid, bounds=None):
        pass

    def get_workspaces(self):
        return [WorkspaceInfo(index=1, is_current=True)]

    def switch_to(self, target_index):
        return target_index == 1
```

### Action Example: Chrome DevTools

```
extensions/core/chrome_devtools/
  extension.json
  actions.py
  static/
    panel.html
```

**extension.json:**
```json
{
  "name": "chrome-devtools",
  "version": "0.1.0",
  "description": "Chrome-specific actions: reload tab, open DevTools, navigate",
  "provider": "core",
  "platforms": ["darwin", "linux", "win32"],
  "capabilities": ["action"],
  "entry_point": "actions:ChromeActions",
  "config_schema": {
    "type": "object",
    "properties": {
      "debug_port": {"type": "integer", "default": 9222}
    }
  }
}
```

**actions.py:**
```python
from hort.ext.types import ActionProvider, ActionInfo, ActionResult

class ChromeActions(ActionProvider):
    def __init__(self):
        self._port = 9222

    def activate(self, config):
        self._port = config.get("debug_port", 9222)

    def get_actions(self):
        return [
            ActionInfo(id="reload", name="Reload Tab",
                       description="Reload the active Chrome tab"),
            ActionInfo(id="devtools", name="Toggle DevTools",
                       description="Open/close Chrome DevTools"),
        ]

    def execute(self, action_id, params=None):
        if action_id == "reload":
            # Use Chrome DevTools Protocol via debug port
            ...
            return ActionResult(success=True, message="Tab reloaded")
        return ActionResult(success=False, message=f"Unknown action: {action_id}")
```

### Command Target Example: Docker Container

```
extensions/core/docker_target/
  extension.json
  target.py
```

**extension.json:**
```json
{
  "name": "docker-target",
  "version": "0.1.0",
  "description": "Execute commands in Docker containers",
  "provider": "core",
  "platforms": ["darwin", "linux", "win32"],
  "capabilities": ["command.target"],
  "entry_point": "target:DockerTarget",
  "config_schema": {
    "type": "object",
    "properties": {
      "container_name": {"type": "string"}
    },
    "required": ["container_name"]
  }
}
```

**target.py:**
```python
import asyncio
from hort.ext.types import CommandTarget, CommandResult

class DockerTarget(CommandTarget):
    def __init__(self):
        self._container = ""

    def activate(self, config):
        self._container = config["container_name"]

    @property
    def target_name(self):
        return f"docker:{self._container}"

    async def execute_command(self, command, timeout=30.0):
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", self._container, "sh", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        return CommandResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )

    async def is_available(self):
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", self._container,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
```

## Cross-Platform Support

### Platform Detection

Extensions declare compatible platforms in their manifest's `platforms` array. Values match Python's `sys.platform`:

| Platform | `sys.platform` |
|---|---|
| macOS | `darwin` |
| Linux | `linux` |
| Windows | `win32` |

The registry only loads extensions compatible with the current platform.

### Conditional Dependencies

Platform-specific Python dependencies use PEP 508 environment markers in `pyproject.toml`:

```toml
dependencies = [
    "pyobjc-framework-Quartz>=11.0; sys_platform == 'darwin'",
    "pyobjc-framework-ApplicationServices>=12.1; sys_platform == 'darwin'",
]
```

This makes `pip install hort` succeed on all platforms. macOS-only packages are only installed on macOS.

### Lazy Import Pattern

Extensions use **lazy imports** in method bodies to avoid `ImportError` at import time:

```python
class MacOSWindowsExtension(PlatformProvider):
    def list_windows(self, app_filter=None):
        from hort.windows import list_windows  # macOS import deferred
        return list_windows(app_filter)
```

The class can be **defined** on any platform. It only fails at runtime if called on the wrong OS — and the registry prevents that by checking `platforms` in the manifest.

## Client-Side Extensions

All extension UIs are built with **Quasar** (Vue 3). Pre-compiled vendor assets are bundled at `hort/static/vendor/`:

| File | Description |
|---|---|
| `vue.global.prod.js` | Vue 3.5.30 runtime |
| `quasar.umd.prod.js` | Quasar 2.18.7 UMD build |
| `quasar.prod.css` | Quasar styles |
| `material-icons.css` | Material Icons font |
| `plotly.min.js` | Plotly.js 2.35.3 (charts) |
| `hort-ext.js` | Extension base class (`HortExtension`) |

### JavaScript Extension Base Class

All client-side extensions inherit from `HortExtension` (defined in `hort/static/vendor/hort-ext.js`). This provides a unified lifecycle and API helpers that mirror the Python-side `ExtensionBase`:

| Python (`ExtensionBase`) | JavaScript (`HortExtension`) |
|---|---|
| `activate(config)` | `setup(app, Quasar)` |
| `deactivate()` | `destroy()` |

```javascript
class MyPanel extends HortExtension {
    static id   = 'my-panel';       // must match server-side extension name
    static name = 'My Panel';

    setup(app, Quasar) {
        // Register a Quasar/Vue component
        app.component('my-panel', {
            template: `
                <q-card class="q-ma-md">
                    <q-card-section>
                        <div class="text-h6">{{ title }}</div>
                    </q-card-section>
                    <q-card-section>
                        <q-btn color="primary" @click="reload">Reload</q-btn>
                    </q-card-section>
                </q-card>
            `,
            setup() {
                const title = Vue.ref('My Extension');
                const reload = () => { /* ... */ };
                return { title, reload };
            }
        });
    }

    destroy() {
        // Clean up intervals, WebSockets, etc.
    }
}
HortExtension.register(MyPanel);
```

**Built-in helpers on every extension instance:**

| Method | Description |
|---|---|
| `api(path, opts)` | `GET /api/ext/<id>/<path>` → JSON |
| `apiPost(path, body)` | `POST /api/ext/<id>/<path>` with JSON body |
| `ws(path)` | Open WebSocket to `/ws/ext/<id>/<path>` |
| `notify(msg, type)` | Show Quasar toast notification |
| `config` | Per-extension config object (set before `setup`) |

**Host app lifecycle:**

```javascript
// After all extension <script> tags have loaded:
HortExtension.activateAll(app, Quasar, extensionConfigs);

// On teardown:
HortExtension.destroyAll();
```

### Server-Side: Static Assets

Return a directory from `get_static_dir()`. The server mounts it at `/ext/<extension-name>/`:

```python
class MyUI(UIProvider):
    def get_static_dir(self):
        return Path(__file__).parent / "static"
```

Assets at `extensions/core/my-ext/static/panel.html` become available at `/ext/my-ext/panel.html`.

### Server-Side: API Routes

Return FastAPI route objects from `get_routes()`:

```python
from fastapi import APIRouter

class MyUI(UIProvider):
    def get_routes(self):
        router = APIRouter(prefix="/api/ext/my-ext")

        @router.get("/data")
        async def get_data():
            return {"status": "ok"}

        return router.routes
```

### Full Client+Server Extension Example

```
extensions/core/system_monitor/
  extension.json
  provider.py              # Python: ActionProvider + UIProvider
  static/
    panel.js               # JS: HortExtension subclass
```

**extension.json:**
```json
{
  "name": "system-monitor",
  "version": "0.1.0",
  "capabilities": ["action", "ui.panel"],
  "entry_point": "provider:SystemMonitor"
}
```

**provider.py:**
```python
import psutil
from pathlib import Path
from fastapi import APIRouter
from hort.ext.types import ExtensionBase, ActionProvider, UIProvider, ActionInfo, ActionResult

class SystemMonitor(ExtensionBase, ActionProvider, UIProvider):
    def get_actions(self):
        return [ActionInfo(id="cpu", name="CPU Usage")]

    def execute(self, action_id, params=None):
        return ActionResult(success=True, data={"cpu": psutil.cpu_percent()})

    def get_static_dir(self):
        return Path(__file__).parent / "static"

    def get_routes(self):
        router = APIRouter(prefix="/api/ext/system-monitor")
        @router.get("/stats")
        async def stats():
            return {"cpu": psutil.cpu_percent(), "mem": psutil.virtual_memory().percent}
        return router.routes
```

**static/panel.js:**
```javascript
class SystemMonitorPanel extends HortExtension {
    static id   = 'system-monitor';
    static name = 'System Monitor';

    setup(app, Quasar) {
        const ext = this;
        app.component('system-monitor-panel', {
            template: `
                <q-card>
                    <q-card-section class="text-h6">System</q-card-section>
                    <q-card-section>
                        <div>CPU: {{ stats.cpu }}%</div>
                        <div>MEM: {{ stats.mem }}%</div>
                    </q-card-section>
                </q-card>
            `,
            setup() {
                const stats = Vue.reactive({ cpu: 0, mem: 0 });
                const poll = async () => {
                    const data = await ext.api('stats');
                    Object.assign(stats, data);
                };
                const timer = setInterval(poll, 2000);
                poll();
                Vue.onUnmounted(() => clearInterval(timer));
                return { stats };
            }
        });
    }
}
HortExtension.register(SystemMonitorPanel);
```

## Future: External Extension Registry

### Vision

Extensions will be fetchable from an external git repository containing community contributions:

```
openhort-extensions/          # external repo
  core/
    macos_windows/
    linux_windows/
    windows_windows/
    docker_target/
    chrome_devtools/
  community/
    my_custom_ext/
```

### Fetching & Caching

```
~/.hort/extensions/           # cached extensions
  core/
    macos_windows@0.1.0/
  community/
    some_ext@1.2.0/
```

The registry will:
1. Check a remote manifest index for available extensions
2. Download compatible extensions on demand
3. Cache them locally with version pinning
4. Verify integrity via checksums

### Version Resolution

Extensions declare their version and compatible hort versions. The resolver picks the latest compatible version:

```json
{
  "name": "linux-windows",
  "version": "0.2.0",
  "hort_compat": ">=0.1.0,<1.0.0"
}
```

## Built-in Extensions

### `core/macos-windows`

The reference platform extension. Provides all four platform capabilities on macOS.

| Capability | Implementation |
|---|---|
| `window.list` | Quartz `CGWindowListCopyWindowInfo` + SkyLight Space lookup |
| `window.capture` | Quartz `CGWindowListCreateImage` → PIL → JPEG |
| `input.simulate` | Quartz `CGEventCreate*` + ApplicationServices AX API |
| `workspace.manage` | SkyLight `CGSCopyManagedDisplaySpaces` + Ctrl+Arrow keystrokes |

**Entry point:** `provider:MacOSWindowsExtension`

**Config:**
- `exclude_apps` (string[]) — app names to filter out
- `capture_nominal_resolution` (bool) — use non-Retina resolution

## Summary

| Concept | Location | Purpose |
|---|---|---|
| Provider interfaces | `hort/ext/types.py` | ABCs the server programs against |
| `PlatformProvider` | `hort/ext/types.py` | Unified ABC combining all platform capabilities |
| Manifest model | `hort/ext/manifest.py` | Pydantic model for `extension.json` |
| Registry | `hort/ext/registry.py` | Discovery, loading, capability resolution |
| Built-in extensions | `hort/extensions/core/<name>/` | Shipped with the package |
| Core macOS ext | `hort/extensions/core/macos_windows/` | macOS platform implementation |
| Core Linux ext | `hort/extensions/core/linux_windows/` | Linux container platform implementation |
