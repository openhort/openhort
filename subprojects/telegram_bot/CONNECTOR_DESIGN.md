# Messaging Connector Architecture

Design document for adding Telegram, WhatsApp, and future messaging platforms as openhort connectors.

## Current Connector Landscape

Existing connectors (LAN, Cloud) are **transport connectors** — they provide network paths to reach the hort UI. A messaging connector is fundamentally different: it's an **interaction connector** that receives commands and sends responses through a chat interface.

```
Transport connectors:  Browser ──[LAN/Cloud]──> hort server ──> WebSocket UI
Messaging connectors:  Telegram ──[Bot API]──> hort server ──> plugin/spirit ──> response ──> Telegram
```

## Unified Connector Base

### ConnectorCapabilities

Each connector declares what it can render. This drives how plugins format their responses.

```python
@dataclass(frozen=True)
class ConnectorCapabilities:
    """What a messaging connector can render to the user."""
    text: bool = True            # Plain text messages
    markdown: bool = False       # Markdown formatting (bold, italic, code, links)
    html: bool = False           # Rich HTML (Telegram supports subset, WhatsApp does not)
    images: bool = False         # Send/receive images (JPEG, PNG)
    files: bool = False          # Send/receive arbitrary files
    inline_buttons: bool = False # Clickable inline buttons with callbacks
    commands: bool = False       # /command style interaction
    javascript: bool = False     # Execute JS (only Mini Apps / WebView)
    location: bool = False       # Send/receive GPS coordinates
    stickers: bool = False       # Sticker support
```

### Platform Capability Matrix

| Capability | Telegram Bot | Telegram Mini App | WhatsApp (Baileys) | Signal | Discord |
|---|---|---|---|---|---|
| `text` | yes | yes | yes | yes | yes |
| `markdown` | yes (MarkdownV2) | yes | limited (*bold* only) | no | yes |
| `html` | yes (subset) | yes (full) | no | no | no |
| `images` | yes (10MB) | yes | yes (16MB) | yes | yes (25MB) |
| `files` | yes (50MB) | yes | yes (100MB) | yes | yes (25MB) |
| `inline_buttons` | yes | yes | yes (list/reply buttons) | no | yes (components) |
| `commands` | yes (/cmd) | N/A | no (prefix-based) | no | yes (/cmd) |
| `javascript` | no | yes (full WebView) | no | no | no |
| `location` | yes | yes | yes | no | no |

### ConnectorBase

```python
class ConnectorBase(ABC):
    """Base class for all messaging connectors."""

    @property
    @abstractmethod
    def connector_id(self) -> str:
        """Unique identifier, e.g. 'telegram', 'whatsapp'."""

    @property
    @abstractmethod
    def capabilities(self) -> ConnectorCapabilities:
        """What this connector can render."""

    @abstractmethod
    async def start(self) -> None:
        """Connect to the messaging platform and begin listening."""

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect gracefully."""

    @abstractmethod
    async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
        """Send a response to a specific chat."""

    # ── Provided by base class (not abstract) ────────

    def set_command_registry(self, registry: CommandRegistry) -> None:
        """Injected by the connector manager at startup."""
        self._command_registry = registry

    async def dispatch(self, message: IncomingMessage) -> None:
        """Route an incoming message to the right handler.
        Called by subclass when a message arrives from the platform.
        """
        # 1. Check ACL
        # 2. Parse command or intent
        # 3. Look up handler in command registry
        # 4. Execute handler
        # 5. Format response for this connector's capabilities
        # 6. Call self.send_response()
```

### TelegramConnector

```python
class TelegramConnector(ConnectorBase):
    connector_id = "telegram"

    capabilities = ConnectorCapabilities(
        text=True,
        markdown=True,
        html=True,           # Telegram supports <b>, <i>, <code>, <a>, <pre>
        images=True,
        files=True,
        inline_buttons=True,
        commands=True,
        javascript=False,    # Unless Mini App
        location=True,
    )
```

### WhatsAppConnector (future)

```python
class WhatsAppConnector(ConnectorBase):
    connector_id = "whatsapp"

    capabilities = ConnectorCapabilities(
        text=True,
        markdown=False,      # Only *bold* and _italic_
        html=False,
        images=True,
        files=True,
        inline_buttons=True, # WhatsApp has reply buttons (max 3) and list buttons (max 10)
        commands=False,       # No native /commands — use prefix like "!" or keyword matching
        javascript=False,
        location=True,
    )
```

## Message Model

### IncomingMessage

Normalized representation of a message from any platform.

```python
@dataclass
class IncomingMessage:
    connector_id: str              # "telegram", "whatsapp"
    chat_id: str                   # Platform-specific chat identifier
    user_id: str                   # Platform-specific user ID
    username: str | None           # Human-readable username (for ACL)
    message_id: str                # For replies/edits

    # Content — exactly one is set
    text: str | None = None        # Plain text (including /commands)
    image: bytes | None = None     # Photo payload
    image_mime: str = ""
    file: bytes | None = None      # File payload
    file_name: str = ""
    file_mime: str = ""
    location: tuple[float, float] | None = None  # (lat, lon)
    callback_data: str | None = None  # Inline button press

    # Context
    is_command: bool = False        # Starts with / (Telegram) or ! (WhatsApp)
    command: str = ""               # Parsed command name without prefix
    command_args: str = ""          # Everything after the command
    reply_to_message_id: str | None = None
```

### ConnectorResponse

What a handler returns — the connector adapts it to platform capabilities.

```python
@dataclass
class ConnectorResponse:
    """Platform-agnostic response. Connector picks the best rendering."""

    # Content — multiple can be set, connector picks what it can render
    text: str | None = None                    # Always works
    markdown: str | None = None                # Falls back to text if unsupported
    html: str | None = None                    # Falls back to markdown → text
    image: bytes | None = None                 # JPEG/PNG bytes
    image_caption: str | None = None
    file: bytes | None = None
    file_name: str = ""
    file_mime: str = ""

    # Interactive elements
    buttons: list[ResponseButton] | None = None  # Falls back to numbered text list

    # If the response requires no message (e.g. just an ACK)
    empty: bool = False


@dataclass(frozen=True)
class ResponseButton:
    label: str
    callback_data: str              # Routed back as IncomingMessage.callback_data
```

### Response Rendering (Fallback Chain)

The connector picks the richest format it supports:

```
html → markdown → text → (strip all formatting)

image + caption → image + text fallback → [image unsupported] text only

buttons → inline keyboard → numbered text list ("Reply 1, 2, 3...")
```

This means a plugin author writes ONE response and every connector renders it appropriately:

```python
return ConnectorResponse(
    html="CPU is <b>92%</b> — <i>high load</i>",
    markdown="CPU is **92%** — *high load*",
    text="CPU is 92% — high load",
    buttons=[
        ResponseButton("Show processes", "cmd:process-manager:list"),
        ResponseButton("Take screenshot", "cmd:screenshot-capture:snap"),
    ],
)
```

- **Telegram** renders the HTML + inline keyboard buttons
- **WhatsApp** renders the text + reply buttons (max 3)
- **Signal** renders the text only (no buttons)

## Command Registration

### How Plugins Register Commands

A new mixin — `ConnectorMixin` — lets any plugin expose commands to messaging connectors.

```python
class ConnectorMixin:
    """Mixin for plugins that want to respond to messaging connector commands."""

    def get_connector_commands(self) -> list[ConnectorCommand]:
        """Return commands this plugin handles. Called once at load time."""
        return []

    async def handle_connector_command(
        self,
        command: str,
        message: IncomingMessage,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorResponse:
        """Handle an incoming command. Must return a response."""
        return ConnectorResponse(text=f"Unknown command: {command}")

    async def handle_connector_intent(
        self,
        message: IncomingMessage,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorResponse | None:
        """Handle a non-command message (photo, file, location).
        Return None to pass to the next handler."""
        return None
```

### ConnectorCommand

```python
@dataclass(frozen=True)
class ConnectorCommand:
    name: str                      # Command name without prefix, e.g. "status"
    description: str               # Short help text (shown in Telegram /help and BotFather)
    plugin_id: str                 # Auto-set by registry
    usage: str = ""                # e.g. "screenshot [app_name]"
    hidden: bool = False           # Don't show in /help listing
    accept_images: bool = False    # This command also accepts attached photos
    accept_files: bool = False     # This command also accepts attached files
```

### Manifest Extension

```json
{
  "name": "system-monitor",
  "connector_commands": [
    {
      "name": "cpu",
      "description": "Show current CPU usage"
    },
    {
      "name": "health",
      "description": "Full system health report"
    }
  ]
}
```

### CommandRegistry

Aggregates commands from all loaded plugins.

```python
class CommandRegistry:
    """Central registry of all connector commands across all plugins."""

    def register_plugin(self, plugin_id: str, commands: list[ConnectorCommand]) -> None:
        """Register commands from a plugin."""

    def get_command(self, name: str) -> tuple[str, ConnectorCommand] | None:
        """Look up a command → (plugin_id, command_def)."""

    def get_all_commands(self) -> list[ConnectorCommand]:
        """All registered commands (for /help generation)."""

    def get_intent_handlers(self, message: IncomingMessage) -> list[tuple[str, ConnectorMixin]]:
        """Find plugins that can handle a non-command message (photo, file, etc.)."""
```

## How Spirits, Llmings, and Extensions Register Commands

### Built-in Commands (hort core)

These always exist, provided by the connector framework itself:

| Command | Description | Source |
|---|---|---|
| `/start` | Welcome + help | Connector core |
| `/help` | List all available commands | Connector core (reads CommandRegistry) |
| `/windows` | List windows | Connector core → hort_client |
| `/screenshot [app]` | Capture window | Connector core → hort_client |
| `/targets` | List targets | Connector core → hort_client |
| `/status` | Server status | Connector core → hort_client |
| `/spaces` | Virtual desktops | Connector core → hort_client |

### Plugin-Provided Commands

Each plugin that implements `ConnectorMixin` adds its own commands:

```
system-monitor:
  /cpu          → "CPU: 45%, Load: 2.1"
  /memory       → "Memory: 8.2/16 GB (51%)"
  /health       → Full system health with buttons to drill down

process-manager:
  /processes    → Top 10 processes by CPU, with "Kill" buttons
  /kill <pid>   → Kill a process (with confirmation button)

clipboard-history:
  /clipboard    → Last 5 clipboard entries
  /clip <n>     → Copy entry #n

screenshot-capture:
  /snap [app]   → Take and send a screenshot (same as /screenshot but from plugin)
  /autosnap     → Toggle auto-capture every N seconds

camera-scan:
  (no /commands — responds to photo intents instead)
  Send a photo → scans for QR/barcodes → returns decoded text

network-monitor:
  /network      → Current bandwidth, connections
  /netstat      → Connection table

disk-usage:
  /disk         → Disk usage per volume
```

### Example Plugin Implementation

```python
class SystemMonitor(PluginBase, ScheduledMixin, MCPMixin, ConnectorMixin):

    def get_connector_commands(self) -> list[ConnectorCommand]:
        return [
            ConnectorCommand(
                name="cpu",
                description="Current CPU usage",
                plugin_id=self.plugin_id,
            ),
            ConnectorCommand(
                name="health",
                description="Full system health report",
                plugin_id=self.plugin_id,
            ),
        ]

    async def handle_connector_command(
        self,
        command: str,
        message: IncomingMessage,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorResponse:
        metrics = await self.store.get("latest") or {}

        if command == "cpu":
            pct = metrics.get("cpu_percent", "?")
            return ConnectorResponse(text=f"CPU: {pct}%")

        if command == "health":
            cpu = metrics.get("cpu_percent", "?")
            mem = metrics.get("mem_percent", "?")

            buttons = [
                ResponseButton("Processes", "cmd:process-manager:processes"),
                ResponseButton("Screenshot", "cmd:screenshot-capture:snap"),
            ]

            if capabilities.html:
                return ConnectorResponse(
                    html=f"<b>CPU:</b> {cpu}%\n<b>Memory:</b> {mem}%",
                    buttons=buttons,
                )
            return ConnectorResponse(
                text=f"CPU: {cpu}%\nMemory: {mem}%",
                buttons=buttons,
            )

        return ConnectorResponse(text=f"Unknown: {command}")
```

### Intent-Based Responses (Photos, Files, Location)

When a user sends a photo (not a /command), the connector routes it through intent handlers:

```python
class CameraScan(PluginBase, MCPMixin, ConnectorMixin):

    def get_connector_commands(self) -> list[ConnectorCommand]:
        return []  # No slash commands

    async def handle_connector_intent(
        self,
        message: IncomingMessage,
        capabilities: ConnectorCapabilities,
    ) -> ConnectorResponse | None:
        if message.image is None:
            return None  # Not for us

        result = await self._analyze(message.image)
        codes = result.get("qr_codes", [])

        if codes:
            text = "Detected:\n" + "\n".join(f"- {c}" for c in codes)
            return ConnectorResponse(text=text)

        return ConnectorResponse(text="No QR codes found in image.")
```

### Callback Routing

Button callbacks use the format `cmd:<plugin_id>:<command>[:args]`.

When a user taps a button:
1. Connector receives `callback_data = "cmd:process-manager:processes"`
2. Dispatcher parses it → `plugin_id="process-manager"`, `command="processes"`
3. Calls `process_manager.handle_connector_command("processes", message, caps)`
4. Response rendered and sent back

Cross-plugin buttons are first-class — system-monitor can offer a button that triggers process-manager.

## Dispatch Flow

```
Platform message arrives
       │
       ▼
  ACL check (is user in allowed_users?)
       │ no → silent drop
       ▼ yes
  Parse message type
       │
       ├── /command → CommandRegistry.get_command(name)
       │       │
       │       ├── Found → plugin.handle_connector_command(name, msg, caps)
       │       │       │
       │       │       ▼
       │       │   ConnectorResponse
       │       │       │
       │       │       ▼
       │       │   connector.send_response(chat_id, response)
       │       │
       │       └── Not found → "Unknown command. /help for list"
       │
       ├── callback_data → parse "cmd:<plugin>:<cmd>[:args]"
       │       │
       │       ▼
       │   Same as /command dispatch
       │
       ├── photo/file/location → iterate ConnectorMixin plugins
       │       │
       │       ▼
       │   First plugin that returns non-None response wins
       │   (or "No handler for this content type")
       │
       └── plain text (no command prefix)
               │
               ▼
           Optional: pass to a "default text handler" plugin
           (e.g. AI chat, translation, note-taking)
           Or: "Send /help for available commands"
```

## Configuration

### Per-Connector Config (hort-config.yaml)

```yaml
connector.telegram:
  enabled: true
  allowed_users:
    - alice_dev
  # Token comes from TELEGRAM_BOT_TOKEN env var (never in config file)

connector.whatsapp:
  enabled: false
  allowed_users:
    - "49170xxxxxxx"    # WhatsApp uses phone numbers, not usernames
```

### Per-Connector Feature Overrides

Connectors can disable certain plugin commands:

```yaml
connector.telegram:
  enabled: true
  allowed_users:
    - alice_dev
  disabled_commands:
    - kill             # Don't expose kill via Telegram
  disabled_plugins:
    - clipboard-history  # Not useful via chat
```

## Registration in hort

### As an Extension

The Telegram connector lives at:
```
hort/extensions/core/telegram_connector/
  extension.json
  provider.py          # TelegramConnector(ConnectorBase)
  static/panel.js      # Optional: UI panel showing bot status, QR to bot, etc.
```

### Manifest

```json
{
  "name": "telegram-connector",
  "version": "0.1.0",
  "description": "Telegram bot connector for remote commands",
  "provider": "core",
  "platforms": ["darwin", "linux"],
  "capabilities": ["connector", "messaging"],
  "entry_point": "provider:TelegramConnector",
  "icon": "ph ph-telegram-logo",
  "plugin_type": "connector",
  "features": {
    "screenshots": { "description": "Send screenshots via bot", "default": true },
    "terminal": { "description": "Execute commands via bot", "default": false },
    "alerts": { "description": "Push system alerts to Telegram", "default": true }
  }
}
```

### Startup

```python
# In ConnectorManager (new component in hort/ext/connectors.py)
async def start_connectors(registry: ExtensionRegistry):
    """Find all messaging connectors and start them."""
    cmd_registry = CommandRegistry()

    # Collect commands from all ConnectorMixin plugins
    for plugin in registry.get_all_plugins():
        if isinstance(plugin, ConnectorMixin):
            commands = plugin.get_connector_commands()
            cmd_registry.register_plugin(plugin.plugin_id, commands)

    # Start each messaging connector
    for ext in registry.get_by_capability("messaging"):
        if isinstance(ext, ConnectorBase):
            ext.set_command_registry(cmd_registry)
            await ext.start()
```

## File Layout

```
hort/ext/
  connectors.py              # NEW: ConnectorBase, ConnectorCapabilities,
                             #       ConnectorResponse, IncomingMessage,
                             #       CommandRegistry, ConnectorMixin,
                             #       ConnectorManager

hort/extensions/core/
  telegram_connector/
    extension.json
    provider.py              # TelegramConnector(ConnectorBase)
    static/panel.js          # Optional status UI panel

  whatsapp_connector/        # Future
    extension.json
    provider.py              # WhatsAppConnector(ConnectorBase)
```

## Relationship to Existing Systems

| System | Relationship to Connectors |
|---|---|
| **MCP tools** | Connectors can call MCP tools, but they're separate. MCP is for AI; connectors are for humans. A plugin can expose both. |
| **Intents** | `handle_connector_intent()` is the messaging equivalent of `handle_photo_intent()`. They share the concept but the connector version returns `ConnectorResponse` instead of raw dicts. Existing `IntentMixin` handlers could be auto-wrapped. |
| **Scheduler** | Scheduled jobs can push messages through connectors (alerts). A plugin's scheduled job calls `connector_manager.broadcast(response)` to send to all connected users. |
| **Documents** | Not directly used by connectors, but a `/docs` command could list and fetch plugin documents. |
| **Config** | Connector config lives in `hort-config.yaml` under `connector.<id>`. Same `ConfigStore` as cloud/lan connectors. |
| **Store/Files** | Connectors themselves don't need persistent storage. Plugins that respond to connector commands use their own stores as usual. |

## Key Design Decisions

1. **Plugins own the commands, not the connector.** The Telegram connector doesn't know about CPU monitoring — it just routes `/cpu` to whatever plugin registered that command. Adding a new plugin automatically adds new bot commands.

2. **Response fallback chain.** Plugin authors write the richest response they want. The connector degrades gracefully. No `if connector == "telegram"` branches in plugin code.

3. **Cross-plugin buttons.** A system-monitor response can include a button that triggers process-manager. The callback routing is centralized in `CommandRegistry`, not hardcoded.

4. **ACL at connector level.** Each connector maintains its own allowed-user list because identity formats differ (Telegram usernames vs WhatsApp phone numbers vs Discord IDs).

5. **Connectors are optional extensions.** If Telegram isn't configured, it's just not loaded. Zero overhead. No changes to the core server.

6. **Silent rejection.** Unauthorized users get no response — the bot appears offline to them. This is a security measure, not a UX choice.
