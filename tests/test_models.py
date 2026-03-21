"""Tests for Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hort.models import (
    ServerInfo,
    StreamConfig,
    WindowBounds,
    WindowInfo,
    WindowListResponse,
)


class TestWindowBounds:
    def test_create(self) -> None:
        b = WindowBounds(x=10.0, y=20.0, width=800.0, height=600.0)
        assert b.x == 10.0
        assert b.y == 20.0
        assert b.width == 800.0
        assert b.height == 600.0

    def test_frozen(self) -> None:
        b = WindowBounds(x=0, y=0, width=100, height=100)
        with pytest.raises(ValidationError):
            b.x = 5  # type: ignore[misc]


class TestWindowInfo:
    def test_create_full(self) -> None:
        w = WindowInfo(
            window_id=42,
            owner_name="Chrome",
            window_name="Tab 1",
            bounds=WindowBounds(x=0, y=0, width=1200, height=800),
            layer=0,
            owner_pid=123,
            is_on_screen=True,
        )
        assert w.window_id == 42
        assert w.owner_name == "Chrome"
        assert w.window_name == "Tab 1"
        assert w.bounds.width == 1200

    def test_defaults(self) -> None:
        w = WindowInfo(
            window_id=1,
            owner_name="App",
            bounds=WindowBounds(x=0, y=0, width=100, height=100),
        )
        assert w.window_name == ""
        assert w.layer == 0
        assert w.owner_pid == 0
        assert w.is_on_screen is True

    def test_frozen(self) -> None:
        w = WindowInfo(
            window_id=1,
            owner_name="App",
            bounds=WindowBounds(x=0, y=0, width=100, height=100),
        )
        with pytest.raises(ValidationError):
            w.window_id = 2  # type: ignore[misc]


class TestWindowListResponse:
    def test_create(self) -> None:
        w = WindowInfo(
            window_id=1,
            owner_name="App",
            bounds=WindowBounds(x=0, y=0, width=100, height=100),
        )
        resp = WindowListResponse(windows=[w], app_names=["App"])
        assert len(resp.windows) == 1
        assert resp.app_names == ["App"]

    def test_serialization(self) -> None:
        w = WindowInfo(
            window_id=1,
            owner_name="App",
            bounds=WindowBounds(x=0, y=0, width=100, height=100),
        )
        resp = WindowListResponse(windows=[w], app_names=["App"])
        data = resp.model_dump()
        assert data["windows"][0]["window_id"] == 1
        assert data["app_names"] == ["App"]


class TestStreamConfig:
    def test_defaults(self) -> None:
        c = StreamConfig(window_id=42)
        assert c.fps == 10
        assert c.quality == 70
        assert c.max_width == 800

    def test_custom(self) -> None:
        c = StreamConfig(window_id=42, fps=30, quality=90, max_width=1920)
        assert c.fps == 30
        assert c.quality == 90
        assert c.max_width == 1920

    def test_fps_bounds(self) -> None:
        with pytest.raises(ValidationError):
            StreamConfig(window_id=1, fps=0)
        with pytest.raises(ValidationError):
            StreamConfig(window_id=1, fps=61)

    def test_quality_bounds(self) -> None:
        with pytest.raises(ValidationError):
            StreamConfig(window_id=1, quality=0)
        with pytest.raises(ValidationError):
            StreamConfig(window_id=1, quality=101)

    def test_max_width_bounds(self) -> None:
        with pytest.raises(ValidationError):
            StreamConfig(window_id=1, max_width=50)
        with pytest.raises(ValidationError):
            StreamConfig(window_id=1, max_width=8000)

    def test_mutable(self) -> None:
        c = StreamConfig(window_id=1)
        c.quality = 90
        assert c.quality == 90

    def test_screen_info_defaults(self) -> None:
        c = StreamConfig(window_id=1)
        assert c.screen_width == 0
        assert c.screen_dpr == 1.0

    def test_screen_info_custom(self) -> None:
        c = StreamConfig(window_id=1, screen_width=1024, screen_dpr=2.0)
        assert c.screen_width == 1024
        assert c.screen_dpr == 2.0


class TestStatusResponse:
    def test_create(self) -> None:
        from hort.models import StatusResponse

        s = StatusResponse(observers=3)
        assert s.observers == 3
        assert s.version == "0.1.0"

    def test_frozen(self) -> None:
        from hort.models import StatusResponse

        s = StatusResponse(observers=1)
        with pytest.raises(ValidationError):
            s.observers = 5  # type: ignore[misc]


class TestServerInfo:
    def test_urls(self) -> None:
        s = ServerInfo(lan_ip="192.168.1.42", http_port=8940, https_port=8950)
        assert s.https_url == "https://192.168.1.42:8950"
        assert s.http_url == "http://192.168.1.42:8940"

    def test_frozen(self) -> None:
        s = ServerInfo(lan_ip="192.168.1.42", http_port=8940, https_port=8950)
        with pytest.raises(ValidationError):
            s.lan_ip = "10.0.0.1"  # type: ignore[misc]
