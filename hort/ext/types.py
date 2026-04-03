"""Abstract base types for extension capabilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hort.models import InputEvent, WindowBounds, WindowInfo


# ===== Data types =====


@dataclass(frozen=True)
class WorkspaceInfo:
    """Cross-platform workspace (macOS Space, Windows Virtual Desktop, Linux Workspace)."""

    index: int  # 1-based
    is_current: bool
    name: str = ""


@dataclass(frozen=True)
class ActionInfo:
    """Metadata for an available action."""

    id: str
    name: str
    description: str = ""
    params_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActionResult:
    """Result of executing an action."""

    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class CommandResult:
    """Result of a command execution."""

    exit_code: int
    stdout: str
    stderr: str


# ===== Provider interfaces =====


class WindowProvider(ABC):
    """Lists and manages windows on a target platform.

    The primary capability for any platform extension.  Implementations
    must translate OS-specific window enumeration into the common
    ``WindowInfo`` model.
    """

    @abstractmethod
    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        """List visible windows, optionally filtered by app name."""

    def get_app_names(self) -> list[str]:
        """Get sorted unique application names from visible windows."""
        return sorted({w.owner_name for w in self.list_windows() if w.window_id >= 0})


class CaptureProvider(ABC):
    """Captures window screenshots as JPEG bytes."""

    @abstractmethod
    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None:
        """Capture a window as JPEG bytes.  Returns ``None`` on failure."""


class InputProvider(ABC):
    """Simulates user input (mouse, keyboard, scroll) on a target platform."""

    @abstractmethod
    def handle_input(
        self, event: InputEvent, bounds: WindowBounds, pid: int = 0
    ) -> None:
        """Process an input event, translating normalised coords to screen coords."""

    @abstractmethod
    def activate_app(
        self, pid: int, bounds: WindowBounds | None = None
    ) -> None:
        """Bring an application window to the foreground."""


class WorkspaceProvider(ABC):
    """Manages workspaces, virtual desktops, or Spaces."""

    @abstractmethod
    def get_workspaces(self) -> list[WorkspaceInfo]:
        """Get all workspaces with the current one marked."""

    def get_current_index(self) -> int:
        """Get the 1-based index of the current workspace."""
        for ws in self.get_workspaces():
            if ws.is_current:
                return ws.index
        return 1

    @abstractmethod
    def switch_to(self, target_index: int) -> bool:
        """Switch to the workspace at the given 1-based index."""


class ActionProvider(ABC):
    """Provides executable actions (Chrome reload, app launch, custom scripts, ...)."""

    @abstractmethod
    def get_actions(self) -> list[ActionInfo]:
        """List available actions."""

    @abstractmethod
    def execute(
        self, action_id: str, params: dict[str, Any] | None = None
    ) -> ActionResult:
        """Execute an action by ID with optional parameters."""


class CommandTarget(ABC):
    """A target that can execute shell commands (local host, container, VM)."""

    @property
    @abstractmethod
    def target_name(self) -> str:
        """Human-readable name for this target."""

    @abstractmethod
    async def execute_command(
        self, command: str, timeout: float = 30.0
    ) -> CommandResult:
        """Execute a shell command on this target."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Check whether this target is reachable."""


class UIProvider(ABC):
    """Provides client-side UI components for the web app."""

    def get_static_dir(self) -> Path | None:
        """Return directory containing static assets to serve."""
        return None

    def get_routes(self) -> list[Any]:
        """Return FastAPI route objects to register."""
        return []


# ===== Unified base classes =====


class PlatformProvider(
    WindowProvider, CaptureProvider, InputProvider, WorkspaceProvider
):
    """Unified interface for a complete platform implementation.

    The server imports this single type and calls methods on it without
    knowing whether it's talking to macOS, Windows, or Linux.  Every
    platform extension (``core/macos_windows``, future ``core/linux_windows``,
    ``core/windows_windows``) must implement this class.

    Example server usage::

        platform = registry.get_provider("window.list", PlatformProvider)
        windows = platform.list_windows()
        frame   = platform.capture_window(windows[0].window_id)
    """


class ExtensionBase(ABC):
    """Unified base class for user-created extensions.

    All extensions — platform providers, action providers, command targets,
    UI panels — should inherit from ``ExtensionBase`` so the registry can
    manage them with a consistent lifecycle.

    Lifecycle::

        ext = MyExtension()
        ext.activate(config)   # called once at load time
        ...                    # extension methods called by the server
        ext.deactivate()       # called on shutdown or hot-reload
    """

    def activate(self, config: dict[str, Any]) -> None:
        """Called once when the extension is loaded.

        Override to accept per-extension configuration from the user's
        config or the manifest's ``config_schema``.
        """

    def deactivate(self) -> None:
        """Called when the extension is unloaded (shutdown / hot-reload).

        Override to clean up resources (open files, connections, threads).
        """
