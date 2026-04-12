"""Tests for the screen watcher — models, capture utils, and full watcher."""

from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass
from typing import Any

import pytest
from PIL import Image

from llmings.core.screen_watcher.capture import (
    crop_region,
    frame_hash,
    frames_differ,
)
from llmings.core.screen_watcher.models import (
    REGION_PRESETS,
    RegionConfig,
    ScreenWatcherConfig,
    WatchRule,
    resolve_region,
)
from llmings.core.screen_watcher.screen_watcher import ScreenWatcher
from hort.signals.models import Signal


# ── Helpers ──────────────────────────────────────────────────────────


def _make_jpeg(width: int = 100, height: int = 100, color: str = "red") -> bytes:
    """Create a simple JPEG image for testing."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@dataclass
class FakeWindow:
    window_id: int
    owner_name: str
    window_name: str
    bounds: Any = None
    layer: int = 0
    owner_pid: int = 1
    is_on_screen: bool = True
    space_index: int = 1


# ── Model tests ─────────────────────────────────────────────────────


class TestRegionConfig:
    def test_defaults(self) -> None:
        r = RegionConfig()
        assert r.preset == "full"

    def test_resolve_preset(self) -> None:
        r = RegionConfig(preset="top_left")
        x, y, w, h = resolve_region(r)
        assert (x, y, w, h) == (0.0, 0.0, 0.5, 0.5)

    def test_resolve_custom(self) -> None:
        r = RegionConfig(preset=None, x=0.1, y=0.2, w=0.3, h=0.4)
        assert resolve_region(r) == (0.1, 0.2, 0.3, 0.4)

    def test_all_presets_defined(self) -> None:
        for name in (
            "full", "left", "right", "top", "bottom",
            "top_left", "top_right", "bottom_left", "bottom_right", "center",
        ):
            assert name in REGION_PRESETS
            x, y, w, h = REGION_PRESETS[name]
            assert 0 <= x <= 1 and 0 <= y <= 1
            assert 0 < w <= 1 and 0 < h <= 1


class TestWatchRule:
    def test_defaults(self) -> None:
        r = WatchRule(name="test")
        assert r.app_filter is None
        assert r.poll_interval == 1.0
        assert r.idle_threshold == 10.0
        assert r.enabled is True

    def test_full_config(self) -> None:
        r = WatchRule(
            name="claude-watch",
            app_filter="iTerm",
            window_filter="*claude*",
            region=RegionConfig(preset="bottom"),
            poll_interval=0.5,
            idle_threshold=5.0,
        )
        assert r.app_filter == "iTerm"
        assert r.window_filter == "*claude*"


# ── Capture utility tests ──────────────────────────────────────────


class TestCropRegion:
    def test_full_region_no_crop(self) -> None:
        jpeg = _make_jpeg(200, 100)
        result = crop_region(jpeg, RegionConfig(preset="full"))
        assert result == jpeg  # same bytes, no processing

    def test_left_half(self) -> None:
        jpeg = _make_jpeg(200, 100)
        result = crop_region(jpeg, RegionConfig(preset="left"))
        img = Image.open(io.BytesIO(result))
        assert img.width == 100  # half of 200
        assert img.height == 100

    def test_top_right(self) -> None:
        jpeg = _make_jpeg(200, 200)
        result = crop_region(jpeg, RegionConfig(preset="top_right"))
        img = Image.open(io.BytesIO(result))
        assert img.width == 100
        assert img.height == 100

    def test_custom_region(self) -> None:
        jpeg = _make_jpeg(400, 400)
        result = crop_region(jpeg, RegionConfig(preset=None, x=0.25, y=0.25, w=0.5, h=0.5))
        img = Image.open(io.BytesIO(result))
        assert img.width == 200
        assert img.height == 200


class TestFrameHash:
    def test_same_bytes_same_hash(self) -> None:
        jpeg = _make_jpeg()
        assert frame_hash(jpeg) == frame_hash(jpeg)

    def test_different_bytes_different_hash(self) -> None:
        a = _make_jpeg(color="red")
        b = _make_jpeg(color="blue")
        assert frame_hash(a) != frame_hash(b)

    def test_frames_differ_none(self) -> None:
        assert frames_differ(None, "abc") is True
        assert frames_differ("abc", None) is True

    def test_frames_differ_same(self) -> None:
        assert frames_differ("abc", "abc") is False

    def test_frames_differ_different(self) -> None:
        assert frames_differ("abc", "xyz") is True


# ── ScreenWatcher integration tests ────────────────────────────────


class TestScreenWatcher:
    """Test the watcher with mock capture and list functions."""

    @pytest.fixture
    def mock_env(self):
        """Set up mock functions and a watcher."""
        windows = [
            FakeWindow(1, "iTerm2", "claude — ~/projects"),
            FakeWindow(2, "Google Chrome", "GitHub"),
            FakeWindow(3, "Finder", "Documents"),
        ]
        frames: dict[int, bytes] = {
            1: _make_jpeg(color="red"),
            2: _make_jpeg(color="green"),
            3: _make_jpeg(color="blue"),
        }
        signals: list[Signal] = []

        def list_windows(app_filter=None):
            result = windows
            if app_filter:
                result = [w for w in result if app_filter.lower() in w.owner_name.lower()]
            return result

        def capture(window_id, max_width=800, quality=70):
            return frames.get(window_id)

        async def emit(signal):
            signals.append(signal)

        return {
            "windows": windows,
            "frames": frames,
            "signals": signals,
            "list_fn": list_windows,
            "capture_fn": capture,
            "emit_fn": emit,
        }

    @pytest.mark.asyncio
    async def test_detects_change(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(name="test", app_filter="iTerm", poll_interval=0.05),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)

        # Change the frame
        mock_env["frames"][1] = _make_jpeg(color="yellow")
        await asyncio.sleep(0.15)
        await watcher.stop()

        changed = [s for s in mock_env["signals"] if s.signal_type == "screen.changed"]
        assert len(changed) >= 2  # initial + color change
        assert changed[0].data["app"] == "iTerm2"
        assert changed[0].data["rule"] == "test"

    @pytest.mark.asyncio
    async def test_detects_idle(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(
                name="idle-test",
                app_filter="iTerm",
                poll_interval=0.05,
                idle_threshold=0.2,  # very short for testing
            ),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        # Wait for idle threshold
        await asyncio.sleep(0.5)
        await watcher.stop()

        idle = [s for s in mock_env["signals"] if s.signal_type == "screen.idle"]
        assert len(idle) >= 1
        assert idle[0].data["rule"] == "idle-test"
        assert idle[0].data["idle_seconds"] >= 0.2

    @pytest.mark.asyncio
    async def test_app_filter(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(name="chrome-only", app_filter="Chrome", poll_interval=0.05),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)
        await watcher.stop()

        changed = [s for s in mock_env["signals"] if s.signal_type == "screen.changed"]
        assert len(changed) >= 1
        assert all(s.data["app"] == "Google Chrome" for s in changed)

    @pytest.mark.asyncio
    async def test_window_filter(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(name="claude-watch", window_filter="*claude*", poll_interval=0.05),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)
        await watcher.stop()

        changed = [s for s in mock_env["signals"] if s.signal_type == "screen.changed"]
        assert len(changed) >= 1
        assert "claude" in changed[0].data["window"].lower()

    @pytest.mark.asyncio
    async def test_region_crop(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(
                name="left-half",
                app_filter="iTerm",
                region=RegionConfig(preset="left"),
                poll_interval=0.05,
            ),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)
        await watcher.stop()

        changed = [s for s in mock_env["signals"] if s.signal_type == "screen.changed"]
        assert len(changed) >= 1
        assert changed[0].data["region"] == "left"

    @pytest.mark.asyncio
    async def test_no_matching_window(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(name="missing", app_filter="NonexistentApp", poll_interval=0.05),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)
        await watcher.stop()

        assert len(mock_env["signals"]) == 0  # nothing to watch

    @pytest.mark.asyncio
    async def test_disabled_rule_skipped(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(name="disabled", app_filter="iTerm", enabled=False),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)
        await watcher.stop()

        assert len(mock_env["signals"]) == 0

    @pytest.mark.asyncio
    async def test_multiple_rules(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(name="iterm", app_filter="iTerm", poll_interval=0.05),
            WatchRule(name="chrome", app_filter="Chrome", poll_interval=0.05),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)
        await watcher.stop()

        rules = {s.data["rule"] for s in mock_env["signals"]}
        assert "iterm" in rules
        assert "chrome" in rules

    @pytest.mark.asyncio
    async def test_get_status(self, mock_env) -> None:
        config = ScreenWatcherConfig(rules=[
            WatchRule(name="status-test", app_filter="iTerm", poll_interval=0.05),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.15)

        status = watcher.get_status()
        assert len(status) == 1
        assert status[0]["name"] == "status-test"
        assert status[0]["window_id"] is not None

        await watcher.stop()

    @pytest.mark.asyncio
    async def test_idle_not_emitted_twice(self, mock_env) -> None:
        """Once idle is emitted, it shouldn't fire again until a change."""
        config = ScreenWatcherConfig(rules=[
            WatchRule(
                name="idle-once",
                app_filter="iTerm",
                poll_interval=0.05,
                idle_threshold=0.1,
            ),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=mock_env["capture_fn"],
            list_windows_fn=mock_env["list_fn"],
            emit_signal_fn=mock_env["emit_fn"],
        )
        await watcher.start()
        await asyncio.sleep(0.5)
        await watcher.stop()

        idle = [s for s in mock_env["signals"] if s.signal_type == "screen.idle"]
        assert len(idle) == 1  # exactly once


class TestScreenWatcherWithSignalBus:
    """Integration: ScreenWatcher + SignalBus + TriggerEngine."""

    @pytest.mark.asyncio
    async def test_change_triggers_reaction(self) -> None:
        """Watcher detects change -> signal -> trigger -> reaction."""
        from hort.signals.bus import SignalBus
        from hort.signals.engine import LogReactionHandler, TriggerEngine
        from hort.signals.models import Reaction, Trigger

        bus = SignalBus()
        engine = TriggerEngine(bus)
        handler = LogReactionHandler()
        engine.set_reaction_handler(handler)
        engine.register_trigger(Trigger(
            trigger_id="screen-change-alert",
            signal_pattern="screen.changed",
            reaction=Reaction(
                reaction_type="tool_call",
                config={"tool": "telegram:send_message", "args": {"text": "Screen changed!"}},
            ),
        ))
        engine.start()

        frames = {1: _make_jpeg(color="red")}
        windows = [FakeWindow(1, "TestApp", "test window")]

        config = ScreenWatcherConfig(rules=[
            WatchRule(name="test", poll_interval=0.05),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=lambda wid, mw=800, q=70: frames.get(wid),
            list_windows_fn=lambda af=None: windows,
            emit_signal_fn=bus.emit,
        )
        await watcher.start()
        await asyncio.sleep(0.15)

        # Change the frame
        frames[1] = _make_jpeg(color="blue")
        await asyncio.sleep(0.15)
        await watcher.stop()
        engine.stop()

        assert len(handler.fired) >= 2  # initial + change
        assert all(r.reaction_type == "tool_call" for r, _ in handler.fired)

    @pytest.mark.asyncio
    async def test_idle_triggers_reaction(self) -> None:
        """Watcher detects idle -> signal -> trigger -> reaction."""
        from hort.signals.bus import SignalBus
        from hort.signals.engine import LogReactionHandler, TriggerEngine
        from hort.signals.models import Reaction, Trigger

        bus = SignalBus()
        engine = TriggerEngine(bus)
        handler = LogReactionHandler()
        engine.set_reaction_handler(handler)
        engine.register_trigger(Trigger(
            trigger_id="idle-notify",
            signal_pattern="screen.idle",
            reaction=Reaction(
                reaction_type="tool_call",
                config={"tool": "telegram:send_message", "args": {"text": "Claude finished!"}},
            ),
        ))
        engine.start()

        frames = {1: _make_jpeg(color="red")}

        config = ScreenWatcherConfig(rules=[
            WatchRule(name="claude", poll_interval=0.05, idle_threshold=0.2),
        ])
        watcher = ScreenWatcher(
            config,
            capture_fn=lambda wid, mw=800, q=70: frames.get(wid),
            list_windows_fn=lambda af=None: [FakeWindow(1, "iTerm", "claude")],
            emit_signal_fn=bus.emit,
        )
        await watcher.start()
        await asyncio.sleep(0.5)
        await watcher.stop()
        engine.stop()

        idle_reactions = [r for r, s in handler.fired]
        assert len(idle_reactions) >= 1
        assert idle_reactions[0].config["tool"] == "telegram:send_message"
