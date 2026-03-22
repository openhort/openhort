"""Tests for hort.controller — HortController message handling."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from hort.controller import HortController
from hort.ext.types import PlatformProvider, WorkspaceInfo
from hort.models import InputEvent, StreamConfig, WindowBounds, WindowInfo
from hort.session import HortRegistry, HortSessionEntry
from hort.targets import TargetInfo, TargetRegistry


# ===== Stub provider =====

_BOUNDS = WindowBounds(x=0, y=0, width=1200, height=800)
_WINDOWS = [
    WindowInfo(window_id=101, owner_name="Chrome", window_name="Tab 1",
               bounds=_BOUNDS, owner_pid=1001),
    WindowInfo(window_id=201, owner_name="Code", window_name="main.py",
               bounds=_BOUNDS, owner_pid=2001),
]


class StubPlatform(PlatformProvider):
    def __init__(self) -> None:
        self.last_input: InputEvent | None = None
        self.last_activated_pid: int | None = None
        self.capture_data: bytes | None = b"\xff\xd8test"
        self.switch_result: bool = True

    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        if app_filter:
            return [w for w in _WINDOWS if app_filter.lower() in w.owner_name.lower()]
        return list(_WINDOWS)

    def capture_window(self, window_id: int, max_width: int = 800, quality: int = 70) -> bytes | None:
        return self.capture_data

    def handle_input(self, event: InputEvent, bounds: WindowBounds, pid: int = 0) -> None:
        self.last_input = event

    def activate_app(self, pid: int, bounds: WindowBounds | None = None) -> None:
        self.last_activated_pid = pid

    def get_workspaces(self) -> list[WorkspaceInfo]:
        return [
            WorkspaceInfo(index=1, is_current=True),
            WorkspaceInfo(index=2, is_current=False),
        ]

    def switch_to(self, target_index: int) -> bool:
        return self.switch_result


# ===== Fixtures =====


@pytest.fixture(autouse=True)
def _reset_registries() -> None:
    TargetRegistry.reset()
    HortRegistry.reset()


@pytest.fixture()
def stub_platform() -> StubPlatform:
    platform = StubPlatform()
    TargetRegistry.get().register(
        "test",
        TargetInfo(id="test", name="Test", provider_type="test"),
        platform,
    )
    return platform


@pytest.fixture()
def controller(stub_platform: StubPlatform) -> HortController:
    ctrl = HortController("test-session")
    ctrl._target_id = "test"  # default to the stub target for most tests
    ws = AsyncMock()
    ctrl.set_websocket(ws)
    entry = HortSessionEntry(user_id="test")
    ctrl.set_session_entry(entry)
    return ctrl


def _sent(ctrl: HortController) -> list[dict[str, Any]]:
    """Extract all messages sent via the mock websocket."""
    ws = ctrl._ws
    msgs = []
    for call in ws.send_text.call_args_list:
        msgs.append(json.loads(call[0][0]))
    return msgs


def _run(ctrl: HortController, msg: dict[str, Any]) -> None:
    asyncio.get_event_loop().run_until_complete(ctrl.handle_message(msg))


# ===== Target management =====


class TestListTargets:
    def test_returns_targets(self, controller: HortController) -> None:
        _run(controller, {"type": "list_targets"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "targets_list"
        assert len(msgs[0]["targets"]) == 1
        assert msgs[0]["targets"][0]["id"] == "test"

    def test_active_reflects_current(self, controller: HortController) -> None:
        controller._target_id = "all"
        _run(controller, {"type": "list_targets"})
        msgs = _sent(controller)
        assert msgs[0]["active"] == "all"


class TestSetTarget:
    def test_switch_target(self, controller: HortController) -> None:
        TargetRegistry.get().register(
            "other",
            TargetInfo(id="other", name="Other", provider_type="other"),
            StubPlatform(),
        )
        _run(controller, {"type": "set_target", "target_id": "other"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "target_changed"
        assert msgs[0]["target_id"] == "other"

    def test_switch_to_all(self, controller: HortController) -> None:
        _run(controller, {"type": "set_target", "target_id": "all"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "target_changed"
        assert msgs[0]["target_id"] == "all"

    def test_switch_unknown_target(self, controller: HortController) -> None:
        _run(controller, {"type": "set_target", "target_id": "nonexistent"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "error"

    def test_switch_resets_stream(self, controller: HortController) -> None:
        controller._entry.stream_config = StreamConfig(window_id=1)
        controller._entry.active_window_id = 1
        TargetRegistry.get().register(
            "other",
            TargetInfo(id="other", name="O", provider_type="o"),
            StubPlatform(),
        )
        _run(controller, {"type": "set_target", "target_id": "other"})
        assert controller._entry.stream_config is None
        assert controller._entry.active_window_id == 0


# ===== Window operations =====


class TestListWindows:
    def test_returns_windows(self, controller: HortController) -> None:
        _run(controller, {"type": "list_windows"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "windows_list"
        assert len(msgs[0]["windows"]) == 2
        assert "Chrome" in msgs[0]["app_names"]

    def test_with_filter(self, controller: HortController) -> None:
        _run(controller, {"type": "list_windows", "app_filter": "chrome"})
        msgs = _sent(controller)
        assert len(msgs[0]["windows"]) == 1
        # app_names comes from unfiltered list
        assert len(msgs[0]["app_names"]) == 2

    def test_no_provider(self, controller: HortController) -> None:
        TargetRegistry.reset()
        _run(controller, {"type": "list_windows"})
        msgs = _sent(controller)
        assert msgs[0]["windows"] == []


class TestProviderForWindow:
    def test_all_mode_not_found(self, controller: HortController) -> None:
        """_provider_for_window returns (None, '') when window not in any target."""
        controller._target_id = "all"
        p, tid = controller._provider_for_window(999999)
        assert p is None
        assert tid == ""

    def test_all_mode_skips_none_provider(self, controller: HortController) -> None:
        """Skips targets whose provider is None."""
        controller._target_id = "all"
        # Use a window_id that only exists in "test" target (101)
        # but register a broken target first — targets are iterated in order
        # and the registry uses a dict so insertion order matters
        reg = TargetRegistry.get()
        # Remove and re-register so "broken" comes before "test" in iteration
        reg.remove("test")
        reg.register("broken", TargetInfo(id="broken", name="B", provider_type="x"), StubPlatform())
        reg._providers["broken"] = None  # type: ignore[assignment]
        platform = StubPlatform()
        reg.register("test", TargetInfo(id="test", name="Test", provider_type="test"), platform)
        p, tid = controller._provider_for_window(101)
        assert p is not None
        assert tid == "test"


class TestListWindowsAllMode:
    def test_aggregates_all_targets(self, controller: HortController) -> None:
        """'all' mode returns windows from every registered target."""
        other = StubPlatform()
        other_bounds = WindowBounds(x=0, y=0, width=800, height=600)
        _OTHER_WIN = [WindowInfo(window_id=999, owner_name="Firefox", window_name="Tab",
                                 bounds=other_bounds, owner_pid=5001)]
        other.list_windows = lambda f=None: _OTHER_WIN if f is None or "firefox" in (f or "").lower() else []  # type: ignore[assignment]
        TargetRegistry.get().register(
            "linux", TargetInfo(id="linux", name="Linux Box", provider_type="linux-docker"), other
        )
        controller._target_id = "all"
        _run(controller, {"type": "list_windows"})
        msgs = _sent(controller)
        wins = msgs[0]["windows"]
        # Should have windows from both targets
        target_ids = {w["target_id"] for w in wins}
        assert "test" in target_ids
        assert "linux" in target_ids
        # Each window has target_name
        assert any(w["target_name"] == "Linux Box" for w in wins)

    def test_all_mode_with_filter(self, controller: HortController) -> None:
        controller._target_id = "all"
        _run(controller, {"type": "list_windows", "app_filter": "Chrome"})
        msgs = _sent(controller)
        assert all("Chrome" in w["owner_name"] for w in msgs[0]["windows"])

    def test_all_mode_skips_none_provider(self, controller: HortController) -> None:
        controller._target_id = "all"
        TargetRegistry.get().register(
            "broken", TargetInfo(id="broken", name="B", provider_type="x"), StubPlatform()
        )
        TargetRegistry.get()._providers["broken"] = None  # type: ignore[assignment]
        _run(controller, {"type": "list_windows"})
        msgs = _sent(controller)
        # Should still return windows from "test" target, skipping "broken"
        assert len(msgs[0]["windows"]) > 0


class TestGetThumbnail:
    def test_with_image(self, controller: HortController) -> None:
        _run(controller, {"type": "get_thumbnail", "window_id": 42})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "thumbnail"
        assert msgs[0]["data"] is not None

    def test_no_capture(self, controller: HortController, stub_platform: StubPlatform) -> None:
        stub_platform.capture_data = None
        _run(controller, {"type": "get_thumbnail", "window_id": 99})
        msgs = _sent(controller)
        assert msgs[0]["data"] is None

    def test_no_provider(self, controller: HortController) -> None:
        TargetRegistry.reset()
        _run(controller, {"type": "get_thumbnail", "window_id": 1})
        msgs = _sent(controller)
        assert msgs[0]["data"] is None

    def test_with_explicit_target_id(self, controller: HortController) -> None:
        """Thumbnail request can specify target_id to route to correct provider."""
        _run(controller, {"type": "get_thumbnail", "window_id": 101, "target_id": "test"})
        msgs = _sent(controller)
        assert msgs[0]["data"] is not None


class TestStreamConfigTarget:
    def test_stores_target_on_entry(self, controller: HortController) -> None:
        _run(controller, {
            "type": "stream_config", "window_id": 101,
            "fps": 10, "quality": 70, "max_width": 800,
            "target_id": "test",
        })
        assert controller._entry.active_target_id == "test"

    def test_resolves_from_all_mode(self, controller: HortController) -> None:
        controller._target_id = "all"
        _run(controller, {
            "type": "stream_config", "window_id": 101,
            "fps": 10, "quality": 70, "max_width": 800,
        })
        # Should resolve to "test" since that's where window 101 lives
        assert controller._entry.active_target_id == "test"

    def test_uses_active_target_when_set(self, controller: HortController) -> None:
        controller._target_id = "test"
        _run(controller, {
            "type": "stream_config", "window_id": 101,
            "fps": 10, "quality": 70, "max_width": 800,
        })
        assert controller._entry.active_target_id == "test"


class TestGetStatus:
    def test_returns_status(self, controller: HortController) -> None:
        _run(controller, {"type": "get_status"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "status"
        assert msgs[0]["observers"] == 0


class TestGetSpaces:
    def test_returns_workspaces(self, controller: HortController) -> None:
        _run(controller, {"type": "get_spaces"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "spaces"
        assert msgs[0]["count"] == 2
        assert msgs[0]["current"] == 1

    def test_no_provider(self, controller: HortController) -> None:
        TargetRegistry.reset()
        _run(controller, {"type": "get_spaces"})
        msgs = _sent(controller)
        assert msgs[0]["count"] == 0


class TestSwitchSpace:
    def test_switch(self, controller: HortController) -> None:
        _run(controller, {"type": "switch_space", "index": 2})
        msgs = _sent(controller)
        assert msgs[0]["ok"] is True

    def test_no_provider(self, controller: HortController) -> None:
        TargetRegistry.reset()
        _run(controller, {"type": "switch_space", "index": 1})
        msgs = _sent(controller)
        assert msgs[0]["ok"] is False


class TestStreamConfig:
    def test_valid(self, controller: HortController) -> None:
        _run(controller, {
            "type": "stream_config", "window_id": 101,
            "fps": 15, "quality": 70, "max_width": 1920,
            "screen_width": 390, "screen_dpr": 3.0,
        })
        msgs = _sent(controller)
        assert msgs[0]["type"] == "stream_config_ack"
        assert controller._entry.active_window_id == 101

    def test_invalid(self, controller: HortController) -> None:
        _run(controller, {"type": "stream_config", "window_id": 1, "fps": 0})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "error"


class TestInput:
    def _setup_stream(self, controller: HortController, window_id: int = 101) -> None:
        """Send stream_config to populate the cached provider + window."""
        _run(controller, {
            "type": "stream_config", "window_id": window_id,
            "fps": 10, "quality": 70, "max_width": 800,
        })

    def test_click(self, controller: HortController, stub_platform: StubPlatform) -> None:
        self._setup_stream(controller, 101)
        _run(controller, {"type": "input", "event_type": "click", "nx": 0.5, "ny": 0.5})
        assert stub_platform.last_input is not None
        assert stub_platform.last_input.type == "click"

    def test_no_cache(self, controller: HortController, stub_platform: StubPlatform) -> None:
        """Input without prior stream_config is silently dropped."""
        controller._entry.active_window_id = 101
        _run(controller, {"type": "input", "event_type": "click", "nx": 0.5, "ny": 0.5})
        assert stub_platform.last_input is None

    def test_no_provider(self, controller: HortController) -> None:
        TargetRegistry.reset()
        controller._entry.active_window_id = 101
        _run(controller, {"type": "input", "event_type": "click", "nx": 0.5, "ny": 0.5})
        # Should not raise

    def test_exception_silenced(self, controller: HortController, stub_platform: StubPlatform) -> None:
        self._setup_stream(controller, 101)

        def boom(*a: Any, **kw: Any) -> None:
            raise RuntimeError("boom")

        stub_platform.handle_input = boom  # type: ignore[assignment]
        _run(controller, {"type": "input", "event_type": "click", "nx": 0.5, "ny": 0.5})
        # Should not raise


class TestProviderRouting:
    def test_uses_target_id_when_set(self, controller: HortController) -> None:
        """When controller has an explicit target_id, uses that provider."""
        other = StubPlatform()
        TargetRegistry.get().register(
            "other",
            TargetInfo(id="other", name="Other", provider_type="o"),
            other,
        )
        controller._target_id = "other"
        _run(controller, {"type": "list_windows"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "windows_list"


class TestHeartbeat:
    def test_ack(self, controller: HortController) -> None:
        _run(controller, {"type": "heartbeat"})
        msgs = _sent(controller)
        assert msgs[0]["type"] == "heartbeat_ack"


class TestUnknown:
    def test_unknown_type(self, controller: HortController) -> None:
        _run(controller, {"type": "unknown_xyz"})
        # Should not raise
