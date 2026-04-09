"""Connector framework — unified messaging interface for Telegram, Discord, etc.

Connectors provide a command-based interface to openhort. Llmings register
commands via ``LlmingBase.get_powers()``, and connectors route messages to them.

Architecture:
  User → Connector (Telegram/Discord/...) → CommandRegistry → Llming → ConnectorResponse → Connector → User

Key classes:
  - ``ConnectorCapabilities`` — what a connector can render (text, images, buttons)
  - ``IncomingMessage`` — normalized input from any platform
  - ``ConnectorResponse`` — platform-agnostic output with fallback chain
  - ``ConnectorCommand`` — command registration
  - ``ConnectorBase`` — abstract base for connectors
  - ``CommandRegistry`` — central command aggregation and dispatch
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConnectorCapabilities:
    """What a connector platform can render."""
    text: bool = True
    markdown: bool = False
    html: bool = False
    images: bool = False
    files: bool = False
    inline_buttons: bool = False
    commands: bool = False
    location: bool = False
    max_text_length: int = 4096


@dataclass
class IncomingMessage:
    """Normalized message from any connector platform."""
    connector_id: str
    chat_id: str
    user_id: str
    username: str | None = None
    text: str | None = None
    image: bytes | None = None
    file_data: bytes | None = None
    file_name: str | None = None
    location: tuple[float, float] | None = None
    callback_data: str | None = None

    @property
    def is_command(self) -> bool:
        return bool(self.text and self.text.startswith("/"))

    @property
    def command(self) -> str:
        if not self.is_command or not self.text:
            return ""
        return self.text.split()[0][1:].split("@")[0].lower()

    @property
    def command_args(self) -> str:
        if not self.is_command or not self.text:
            return ""
        parts = self.text.split(maxsplit=1)
        return parts[1] if len(parts) > 1 else ""


@dataclass(frozen=True)
class ResponseButton:
    """Interactive button in a connector response."""
    label: str
    callback_data: str


@dataclass
class ConnectorResponse:
    """Platform-agnostic response. Connector picks best format it supports.

    Rendering priority: html → markdown → text, buttons → text list.
    """
    text: str | None = None
    markdown: str | None = None
    html: str | None = None
    image: bytes | None = None
    image_caption: str | None = None
    buttons: list[list[ResponseButton]] | None = None  # rows of buttons

    @staticmethod
    def simple(text: str) -> ConnectorResponse:
        return ConnectorResponse(text=text)

    @staticmethod
    def with_image(image: bytes, caption: str = "", mime: str = "image/jpeg") -> ConnectorResponse:
        return ConnectorResponse(image=image, image_caption=caption, text=caption)


@dataclass(frozen=True)
class ConnectorCommand:
    """A command registered by a plugin or the system."""
    name: str
    description: str
    plugin_id: str = ""  # empty = system command
    usage: str = ""
    hidden: bool = False
    accept_images: bool = False
    accept_files: bool = False
    system: bool = False  # True = cannot be overridden by plugins


class ConnectorBase(ABC):
    """Abstract base for messaging connectors (Telegram, Discord, etc.)."""

    @property
    @abstractmethod
    def connector_id(self) -> str:
        """Unique ID: 'telegram', 'discord', 'whatsapp'."""

    @property
    @abstractmethod
    def capabilities(self) -> ConnectorCapabilities:
        """What this connector can render."""

    @abstractmethod
    async def start(self) -> None:
        """Start the connector (polling, webhook, etc.)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the connector gracefully."""

    @abstractmethod
    async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
        """Send a response to a specific chat. Connector adapts to its capabilities."""

    def render_text(self, response: ConnectorResponse) -> str:
        """Pick the best text format for this connector's capabilities."""
        caps = self.capabilities
        if caps.html and response.html:
            return response.html
        if caps.markdown and response.markdown:
            return response.markdown
        return response.text or ""



class CommandRegistry:
    """Central registry of all commands from system + plugins."""

    def __init__(self) -> None:
        self._commands: dict[str, tuple[str, ConnectorCommand]] = {}  # name → (llming_id, cmd)
        self._llmings: dict[str, Any] = {}  # llming_id → LlmingBase instance
        self._plugins = self._llmings  # backward-compatible alias

    def register_system(self, commands: list[ConnectorCommand]) -> None:
        """Register system commands (cannot be overridden)."""
        for cmd in commands:
            self._commands[cmd.name] = ("", cmd)

    def register_llming(self, llming_id: str, llming: Any, commands: list[ConnectorCommand]) -> None:
        """Register llming commands. System commands take priority.

        Accepts any LlmingBase instance with handle_connector_command().
        """
        self._llmings[llming_id] = llming
        for cmd in commands:
            if cmd.name in self._commands and self._commands[cmd.name][1].system:
                continue  # system command — cannot override
            self._commands[cmd.name] = (llming_id, ConnectorCommand(
                name=cmd.name, description=cmd.description, plugin_id=llming_id,
                usage=cmd.usage, hidden=cmd.hidden, accept_images=cmd.accept_images,
            ))

    # Backward-compatible alias
    register_plugin = register_llming

    def get_command(self, name: str) -> tuple[str, ConnectorCommand] | None:
        """Look up a command by name. Returns (plugin_id, command) or None."""
        return self._commands.get(name)

    def get_all_commands(self) -> list[ConnectorCommand]:
        """All non-hidden commands, sorted by name."""
        return sorted(
            [cmd for _, cmd in self._commands.values() if not cmd.hidden],
            key=lambda c: c.name,
        )

    def get_llming(self, llming_id: str) -> Any:
        """Get the llming instance for handling a command."""
        return self._llmings.get(llming_id)

    # Backward-compatible alias
    get_plugin = get_llming

    async def dispatch(
        self, message: IncomingMessage, capabilities: ConnectorCapabilities
    ) -> ConnectorResponse | None:
        """Dispatch a command message to the appropriate handler."""
        if not message.is_command:
            return None

        entry = self.get_command(message.command)
        if entry is None:
            return ConnectorResponse.simple(f"Unknown command: /{message.command}\nSend /help for available commands.")

        plugin_id, cmd = entry
        if cmd.system:
            # System commands are handled by the connector itself
            return None  # caller handles system commands

        plugin = self.get_llming(plugin_id)
        if plugin is None:
            return ConnectorResponse.simple(f"Llming '{plugin_id}' not available.")

        result = await plugin.handle_connector_command(message.command, message, capabilities)
        return result or ConnectorResponse.simple(f"Command /{message.command} returned no response.")
