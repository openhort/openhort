"""Pydantic models for the remote window viewer."""

from pydantic import BaseModel, ConfigDict, Field


class WindowBounds(BaseModel):
    """Rectangle bounds of a window."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    width: float
    height: float


class WindowInfo(BaseModel):
    """Information about a single macOS window."""

    model_config = ConfigDict(frozen=True)

    window_id: int
    owner_name: str
    window_name: str = ""
    bounds: WindowBounds
    layer: int = 0
    owner_pid: int = 0
    is_on_screen: bool = True
    space_index: int = 0


class WindowListResponse(BaseModel):
    """Response for the window list API."""

    model_config = ConfigDict(frozen=True)

    windows: list[WindowInfo]
    app_names: list[str]


class StreamConfig(BaseModel):
    """WebSocket stream configuration sent by the client."""

    window_id: int
    fps: int = Field(default=10, ge=1, le=60)
    quality: int = Field(default=70, ge=1, le=100)
    max_width: int = Field(default=800, ge=100, le=7680)
    screen_width: int = Field(default=0, ge=0, le=7680)
    screen_dpr: float = Field(default=1.0, ge=0.5, le=4.0)
    codec: str = Field(default="jpeg")  # "jpeg", "vp8", "vp9"


class InputEvent(BaseModel):
    """Remote input event sent from the client."""

    type: str  # "click", "double_click", "right_click", "move", "scroll", "key"
    nx: float = Field(default=0.0, ge=0.0, le=1.0)
    ny: float = Field(default=0.0, ge=0.0, le=1.0)
    dx: float = 0.0
    dy: float = 0.0
    key: str = ""
    modifiers: list[str] = Field(default_factory=list)


class StatusResponse(BaseModel):
    """Server status information."""

    model_config = ConfigDict(frozen=True)

    observers: int
    version: str = "0.1.0"


class ServerInfo(BaseModel):
    """Server connection information."""

    model_config = ConfigDict(frozen=True)

    lan_ip: str
    http_port: int
    https_port: int

    @property
    def https_url(self) -> str:
        """Full HTTPS URL for the server."""
        return f"https://{self.lan_ip}:{self.https_port}"

    @property
    def http_url(self) -> str:
        """Full HTTP URL for the server."""
        return f"http://{self.lan_ip}:{self.http_port}"
