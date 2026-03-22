"""Tests for hort.session — session entry and registry."""

from __future__ import annotations

from hort.models import StreamConfig
from hort.session import HortRegistry, HortSessionEntry


class TestHortSessionEntry:
    def test_defaults(self) -> None:
        entry = HortSessionEntry(user_id="u1")
        assert entry.user_id == "u1"
        assert entry.stream_config is None
        assert entry.stream_ws is None
        assert entry.active_window_id == 0
        assert entry.observer_id == 0

    def test_with_stream_config(self) -> None:
        config = StreamConfig(window_id=42, fps=15)
        entry = HortSessionEntry(user_id="u1", stream_config=config)
        assert entry.stream_config is not None
        assert entry.stream_config.window_id == 42


class TestHortRegistry:
    def setup_method(self) -> None:
        HortRegistry.reset()

    def test_singleton(self) -> None:
        r1 = HortRegistry.get()
        r2 = HortRegistry.get()
        assert r1 is r2

    def test_register_and_get(self) -> None:
        registry = HortRegistry.get()
        entry = HortSessionEntry(user_id="u1")
        registry.register("s1", entry)
        assert registry.get_session("s1") is entry

    def test_next_observer_id(self) -> None:
        registry = HortRegistry.get()
        assert registry.next_observer_id() == 1
        assert registry.next_observer_id() == 2
        assert registry.next_observer_id() == 3

    def test_observer_count_zero(self) -> None:
        registry = HortRegistry.get()
        assert registry.observer_count() == 0

    def test_observer_count_with_stream(self) -> None:
        registry = HortRegistry.get()
        entry = HortSessionEntry(user_id="u1", stream_ws="mock_ws")
        registry.register("s1", entry)
        assert registry.observer_count() == 1

    def test_observer_count_no_stream(self) -> None:
        registry = HortRegistry.get()
        entry = HortSessionEntry(user_id="u1")
        registry.register("s1", entry)
        assert registry.observer_count() == 0

    def test_observer_count_mixed(self) -> None:
        registry = HortRegistry.get()
        registry.register("s1", HortSessionEntry(user_id="u1", stream_ws="ws"))
        registry.register("s2", HortSessionEntry(user_id="u2"))
        registry.register("s3", HortSessionEntry(user_id="u3", stream_ws="ws"))
        assert registry.observer_count() == 2

    def test_reset_clears_counter(self) -> None:
        registry = HortRegistry.get()
        registry.next_observer_id()
        registry.next_observer_id()
        HortRegistry.reset()
        registry = HortRegistry.get()
        assert registry.next_observer_id() == 1
