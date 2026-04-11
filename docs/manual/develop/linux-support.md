# Linux Support

openhort runs natively on Linux via the `linux-native` extension, which uses X11 tools for window management, screen capture, and input simulation. The entire server can be deployed as a Docker container with a virtual X11 desktop.

## Architecture

```mermaid
flowchart TD
    subgraph Container ["Ubuntu Container"]
        subgraph X11 ["X11 Desktop"]
            Xvfb["Xvfb :99<br/>Virtual Framebuffer"]
            FM["Fluxbox<br/>Window Manager"]
            Apps["X11 Applications<br/>xterm, etc."]
        end

        subgraph Server ["openhort Server"]
            FA["FastAPI<br/>:8940"]
            LP["LinuxNativeExtension<br/>PlatformProvider"]
            TC["Telegram Connector"]
            P2P["P2P / Relay"]
        end

        subgraph Tools ["X11 CLI Tools"]
            wmctrl["wmctrl<br/>window listing"]
            xdotool["xdotool<br/>input simulation"]
            import_["import<br/>screenshot capture"]
        end

        LP -->|"subprocess"| wmctrl
        LP -->|"subprocess"| xdotool
        LP -->|"subprocess"| import_
        wmctrl --> Xvfb
        xdotool --> Xvfb
        import_ --> Xvfb
        Xvfb --- FM
        FM --- Apps
    end

    Phone["Phone / Tablet"] -->|"WebSocket / P2P"| FA
    Telegram["Telegram Bot"] -->|"Bot API"| TC
```

## Two Extension Models

openhort has two distinct Linux extensions for different use cases:

| Extension | Directory | Use Case | How It Works |
|-----------|-----------|----------|--------------|
| **linux-native** | `llmings/core/linux_native/` | Server runs **on** Linux | Calls X11 tools directly via `subprocess` |
| **linux-windows** | `llmings/core/linux_windows/` | Server runs on **macOS**, controls a Linux container | Calls X11 tools via `docker exec` |

```mermaid
flowchart LR
    subgraph native ["linux-native (this doc)"]
        direction TB
        SN["openhort server"] -->|"subprocess"| TN["wmctrl / xdotool"]
    end

    subgraph docker ["linux-windows (existing)"]
        direction TB
        SD["openhort server<br/>(macOS host)"] -->|"docker exec"| TD["wmctrl / xdotool<br/>(container)"]
    end
```

## Platform Provider

`LinuxNativeExtension` implements the full `PlatformProvider` interface:

```mermaid
classDiagram
    class PlatformProvider {
        <<interface>>
        +list_windows(app_filter) list~WindowInfo~
        +get_app_names() list~str~
        +capture_window(window_id, max_width, quality) bytes
        +handle_input(event, bounds, pid) void
        +activate_app(pid, bounds) void
        +get_workspaces() list~WorkspaceInfo~
        +switch_to(target_index) bool
    }

    class LinuxNativeExtension {
        -_display: str
        -_env() dict
        -_exec_sync(cmd) tuple
        -_exec_binary(cmd) tuple
        -_get_screen_size() tuple
    }

    PlatformProvider <|-- LinuxNativeExtension
```

### Capability Mapping

| Capability | X11 Tool | Command |
|-----------|----------|---------|
| Window listing | `wmctrl` | `wmctrl -l -p -x -G` |
| App names | `wmctrl` | Extracted from WM_CLASS |
| Screenshot (window) | ImageMagick | `import -window 0x... jpeg:-` |
| Screenshot (desktop) | ImageMagick | `import -window root jpeg:-` |
| Mouse click/move | `xdotool` | `xdotool mousemove X Y click 1` |
| Keyboard input | `xdotool` | `xdotool type --` or `xdotool key` |
| Window activation | `wmctrl` | `wmctrl -i -a <wid>` |
| Workspace list | `wmctrl` | `wmctrl -d` |
| Workspace switch | `wmctrl` | `wmctrl -s <index>` |
| Screen dimensions | `xdpyinfo` | `xdpyinfo | grep dimensions` |

### Desktop Capture

The virtual "Desktop" entry (`window_id=-1`) captures the full X11 root window, matching the macOS behavior where `DESKTOP_WINDOW_ID=-1` triggers `CGDisplayCreateImage`. On Linux this maps to `import -window root`.

## Deployment

### Quick Start

```bash
cd deploy/linux
docker compose up -d
# Open http://localhost:8940
```

### With Telegram Bot

```bash
TELEGRAM_BOT_TOKEN=your_token docker compose up -d
```

### With P2P Support

P2P WebRTC requires `--network=host` so ICE candidates use the host's real IP instead of Docker's internal network:

```bash
docker run -d --network=host --restart=unless-stopped \
  --name openhort-linux \
  -e LLMING_AUTH_SECRET=your_secret \
  -e TELEGRAM_BOT_TOKEN=your_token \
  openhort-linux
```

!!! warning "Docker Desktop on macOS"
    `--network=host` on Docker Desktop (macOS/Windows) works differently than on native Linux Docker. On macOS it maps to the VM's network stack, which still allows P2P to function but may behave differently than true host networking on a Linux host.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLMING_AUTH_SECRET` | (required) | Authentication secret for API access |
| `TELEGRAM_BOT_TOKEN` | (optional) | Telegram bot token for connector |
| `DISPLAY` | `:99` | X11 display for Xvfb |
| `HORT_RESOLUTION` | `1920x1080x24` | Virtual framebuffer resolution |
| `HORT_NO_DEMO` | (unset) | Set to skip launching demo X11 windows |
| `HORT_HTTP_PORT` | `8940` | HTTP server port |

## Container Startup Sequence

```mermaid
sequenceDiagram
    participant E as entrypoint.sh
    participant X as Xvfb
    participant F as Fluxbox
    participant A as Demo Apps
    participant S as uvicorn

    E->>X: Start virtual framebuffer (:99)
    E->>E: Wait for xdpyinfo ready
    E->>F: Start window manager
    E->>A: Launch xterm, xeyes (unless HORT_NO_DEMO)
    E->>S: Start openhort server
    Note over S: Registers local-linux target<br/>via LinuxNativeExtension
    S->>S: Telegram polling starts
```

## Target Registration

When `sys.platform == "linux"`, the server's `_register_targets()` automatically creates a `local-linux` target:

```python title="hort/app.py"
if sys.platform == "linux":
    from llmings.core.linux_native.provider import LinuxNativeExtension
    ext = LinuxNativeExtension()
    ext.activate({})
    registry.register(
        "local-linux",
        TargetInfo(id="local-linux", name="This Linux", provider_type="linux"),
        ext,
    )
```

This mirrors the macOS path which registers `local-macos` with `MacOSWindowsExtension`.

## Key Files

| File | Purpose |
|------|---------|
| `llmings/core/linux_native/provider.py` | `LinuxNativeExtension` — native X11 platform provider |
| `llmings/core/linux_native/extension.json` | Extension manifest (`platforms: ["linux"]`) |
| `deploy/linux/Dockerfile` | Ubuntu 24.04 server image |
| `deploy/linux/entrypoint.sh` | Xvfb + fluxbox + server startup |
| `deploy/linux/docker-compose.yml` | One-command deployment |

## System Requirements (Native Linux)

For running openhort directly on a Linux host (not in Docker):

- Python 3.12+
- X11 display server (Xorg or Xvfb for headless)
- Window manager (any EWMH-compliant: fluxbox, openbox, etc.)
- `wmctrl`, `xdotool`, `imagemagick`, `x11-utils`
- Poetry for dependency management

```bash
# Ubuntu/Debian
sudo apt install wmctrl xdotool imagemagick x11-utils

# Install and run
poetry install
DISPLAY=:0 poetry run python run.py
```
