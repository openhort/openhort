"""Tests for hort.stream — binary WebSocket stream transport."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from starlette.websockets import WebSocketDisconnect

from hort.ext.types import PlatformProvider, WorkspaceInfo
from hort.models import InputEvent, StreamConfig, WindowBounds, WindowInfo
from hort.session import HortRegistry, HortSessionEntry
from hort.stream import _effective_max_width, _raise_window, run_stream
from hort.targets import TargetInfo, TargetRegistry


# Stub provider for stream tests

class _StubPlatform(PlatformProvider):
    def __init__(self, jpeg: bytes = b"\xff\xd8stub") -> None:
        self._jpeg = jpeg
        self.activated_pid: int | None = None

    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        return [WindowInfo(
            window_id=1, owner_name="App", window_name="W",
            bounds=WindowBounds(x=0, y=0, width=100, height=100),
            owner_pid=123, space_index=1,
        )]

    def capture_window(self, window_id: int, max_width: int = 800, quality: int = 70) -> bytes | None:
        return self._jpeg

    def handle_input(self, event: InputEvent, bounds: WindowBounds, pid: int = 0) -> None:
        pass

    def activate_app(self, pid: int, bounds: WindowBounds | None = None) -> None:
        self.activated_pid = pid

    def get_workspaces(self) -> list[WorkspaceInfo]:
        return [WorkspaceInfo(index=1, is_current=True)]

    def switch_to(self, target_index: int) -> bool:
        return True


@pytest.fixture(autouse=True)
def _reset() -> None:
    HortRegistry.reset()
    TargetRegistry.reset()


@pytest.fixture()
def stub_platform() -> _StubPlatform:
    platform = _StubPlatform()
    TargetRegistry.get().register(
        "test",
        TargetInfo(id="test", name="Test", provider_type="test"),
        platform,
    )
    return platform


class TestEffectiveMaxWidth:
    def test_caps_to_client_resolution(self) -> None:
        assert _effective_max_width(390, 3.0, 3840) == 1170

    def test_uses_max_width_when_smaller(self) -> None:
        assert _effective_max_width(1920, 1.0, 800) == 800

    def test_no_screen_info(self) -> None:
        assert _effective_max_width(0, 1.0, 1200) == 1200


class TestRaiseWindow:
    def test_raises_window(self, stub_platform: _StubPlatform) -> None:
        _raise_window(1, stub_platform)
        assert stub_platform.activated_pid == 123

    def test_no_window_found(self, stub_platform: _StubPlatform) -> None:
        _raise_window(99999, stub_platform)
        assert stub_platform.activated_pid is None

    def test_no_pid(self) -> None:
        class NoPidPlatform(_StubPlatform):
            def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
                return [WindowInfo(
                    window_id=1, owner_name="App", window_name="W",
                    bounds=WindowBounds(x=0, y=0, width=100, height=100),
                    owner_pid=0,
                )]
        p = NoPidPlatform()
        _raise_window(1, p)
        assert p.activated_pid is None


class TestRunStream:
    @pytest.mark.asyncio
    async def test_no_session(self) -> None:
        ws = AsyncMock()
        registry = HortRegistry.get()
        await run_stream(ws, "nonexistent", registry)
        ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_supersedes_existing(self, stub_platform: _StubPlatform) -> None:
        registry = HortRegistry.get()
        old_ws = AsyncMock()
        config = StreamConfig(window_id=1, fps=60)
        entry = HortSessionEntry(user_id="u1", stream_ws=old_ws, stream_config=config)
        registry.register("s1", entry)

        new_ws = AsyncMock()
        new_ws.send_bytes = AsyncMock(side_effect=WebSocketDisconnect())

        await run_stream(new_ws, "s1", registry)
        old_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_supersede_close_fails(self, stub_platform: _StubPlatform) -> None:
        registry = HortRegistry.get()
        old_ws = AsyncMock()
        old_ws.close = AsyncMock(side_effect=Exception("dead"))
        config = StreamConfig(window_id=1, fps=60)
        entry = HortSessionEntry(user_id="u1", stream_ws=old_ws, stream_config=config)
        registry.register("s1", entry)

        new_ws = AsyncMock()
        new_ws.send_bytes = AsyncMock(side_effect=WebSocketDisconnect())
        await run_stream(new_ws, "s1", registry)

    @pytest.mark.asyncio
    async def test_sends_frames(self, stub_platform: _StubPlatform) -> None:
        registry = HortRegistry.get()
        config = StreamConfig(window_id=1, fps=60)
        entry = HortSessionEntry(user_id="u1", stream_config=config, active_target_id="test")
        registry.register("s1", entry)

        ws = AsyncMock()
        count = 0

        async def send_bytes_effect(data: bytes) -> None:
            nonlocal count
            count += 1
            if count >= 2:
                raise WebSocketDisconnect()

        ws.send_bytes = AsyncMock(side_effect=send_bytes_effect)

        with patch("hort.stream.asyncio.sleep", return_value=None):
            await run_stream(ws, "s1", registry)

        assert count == 2
        assert entry.stream_ws is None

    @pytest.mark.asyncio
    async def test_capture_failure(self, stub_platform: _StubPlatform) -> None:
        stub_platform._jpeg = None  # type: ignore[assignment]
        registry = HortRegistry.get()
        config = StreamConfig(window_id=999, fps=60)
        control_ws = AsyncMock()
        entry = HortSessionEntry(user_id="u1", stream_config=config, websocket=control_ws)
        registry.register("s1", entry)

        ws = AsyncMock()
        call_count = 0

        async def mock_sleep(t: float) -> None:
            nonlocal call_count
            call_count += 1
            # First call is the 1.0s sleep after capture failure
            # Second call would be 0.1s waiting for new config (config was reset to None)
            if call_count >= 2:
                raise WebSocketDisconnect()

        with patch("hort.stream.asyncio.sleep", side_effect=mock_sleep):
            await run_stream(ws, "s1", registry)

        control_ws.send_text.assert_called()
        # After capture failure, stream_config should be reset to None
        assert entry.stream_config is None

    @pytest.mark.asyncio
    async def test_control_ws_error_ignored(self, stub_platform: _StubPlatform) -> None:
        stub_platform._jpeg = None  # type: ignore[assignment]
        registry = HortRegistry.get()
        config = StreamConfig(window_id=999, fps=60)
        control_ws = AsyncMock()
        control_ws.send_text = AsyncMock(side_effect=Exception("dead"))
        entry = HortSessionEntry(user_id="u1", stream_config=config, websocket=control_ws)
        registry.register("s1", entry)

        ws = AsyncMock()

        async def mock_sleep(t: float) -> None:
            raise WebSocketDisconnect()

        with patch("hort.stream.asyncio.sleep", side_effect=mock_sleep):
            await run_stream(ws, "s1", registry)

    @pytest.mark.asyncio
    async def test_generic_exception(self, stub_platform: _StubPlatform) -> None:
        stub_platform._jpeg = None  # type: ignore[assignment]
        registry = HortRegistry.get()
        config = StreamConfig(window_id=1, fps=60)
        entry = HortSessionEntry(user_id="u1", stream_config=config)
        registry.register("s1", entry)

        ws = AsyncMock()

        # Make _get_provider raise
        with patch("hort.stream._get_provider", side_effect=RuntimeError("boom")):
            await run_stream(ws, "s1", registry)

        assert entry.stream_ws is None

    @pytest.mark.asyncio
    async def test_waits_for_config(self, stub_platform: _StubPlatform) -> None:
        registry = HortRegistry.get()
        entry = HortSessionEntry(user_id="u1")
        registry.register("s1", entry)

        ws = AsyncMock()
        sleep_count = 0

        async def mock_sleep(t: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count == 1:
                entry.stream_config = StreamConfig(window_id=1, fps=60)
            elif sleep_count >= 3:
                raise WebSocketDisconnect()

        with patch("hort.stream.asyncio.sleep", side_effect=mock_sleep):
            await run_stream(ws, "s1", registry)

        assert sleep_count >= 2

    @pytest.mark.asyncio
    async def test_no_provider_waits(self) -> None:
        """When no provider is registered, stream waits."""
        # No target registered (autouse fixture reset everything)
        registry = HortRegistry.get()
        config = StreamConfig(window_id=1, fps=60)
        entry = HortSessionEntry(user_id="u1", stream_config=config)
        registry.register("s1", entry)

        ws = AsyncMock()
        sleep_count = 0

        async def mock_sleep(t: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise WebSocketDisconnect()

        with patch("hort.stream.asyncio.sleep", side_effect=mock_sleep):
            await run_stream(ws, "s1", registry)

        assert sleep_count >= 1
