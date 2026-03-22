"""Tests for hort.targets — target registry."""

from __future__ import annotations

from hort.ext.types import PlatformProvider, WorkspaceInfo
from hort.models import InputEvent, WindowBounds, WindowInfo
from hort.targets import TargetInfo, TargetRegistry


class StubProvider(PlatformProvider):
    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        return []

    def capture_window(self, window_id: int, max_width: int = 800, quality: int = 70) -> bytes | None:
        return None

    def handle_input(self, event: InputEvent, bounds: WindowBounds, pid: int = 0) -> None:
        pass

    def activate_app(self, pid: int, bounds: WindowBounds | None = None) -> None:
        pass

    def get_workspaces(self) -> list[WorkspaceInfo]:
        return [WorkspaceInfo(index=1, is_current=True)]

    def switch_to(self, target_index: int) -> bool:
        return True


class TestTargetRegistry:
    def setup_method(self) -> None:
        TargetRegistry.reset()

    def test_singleton(self) -> None:
        r1 = TargetRegistry.get()
        r2 = TargetRegistry.get()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = TargetRegistry.get()
        TargetRegistry.reset()
        r2 = TargetRegistry.get()
        assert r1 is not r2

    def test_register_and_get(self) -> None:
        reg = TargetRegistry.get()
        provider = StubProvider()
        info = TargetInfo(id="t1", name="Test", provider_type="test")
        reg.register("t1", info, provider)
        assert reg.get_provider("t1") is provider
        assert reg.get_info("t1") is info

    def test_first_registered_is_default(self) -> None:
        reg = TargetRegistry.get()
        p1 = StubProvider()
        p2 = StubProvider()
        reg.register("t1", TargetInfo(id="t1", name="First", provider_type="a"), p1)
        reg.register("t2", TargetInfo(id="t2", name="Second", provider_type="b"), p2)
        assert reg.default_id == "t1"
        assert reg.get_default() is p1

    def test_set_default(self) -> None:
        reg = TargetRegistry.get()
        p1 = StubProvider()
        p2 = StubProvider()
        reg.register("t1", TargetInfo(id="t1", name="A", provider_type="a"), p1)
        reg.register("t2", TargetInfo(id="t2", name="B", provider_type="b"), p2)
        reg.default_id = "t2"
        assert reg.get_default() is p2

    def test_set_default_invalid(self) -> None:
        reg = TargetRegistry.get()
        p = StubProvider()
        reg.register("t1", TargetInfo(id="t1", name="A", provider_type="a"), p)
        reg.default_id = "nonexistent"
        assert reg.default_id == "t1"  # unchanged

    def test_get_default_empty(self) -> None:
        assert TargetRegistry.get().get_default() is None

    def test_get_provider_missing(self) -> None:
        assert TargetRegistry.get().get_provider("nope") is None

    def test_get_info_missing(self) -> None:
        assert TargetRegistry.get().get_info("nope") is None

    def test_list_targets(self) -> None:
        reg = TargetRegistry.get()
        reg.register("t1", TargetInfo(id="t1", name="A", provider_type="a"), StubProvider())
        reg.register("t2", TargetInfo(id="t2", name="B", provider_type="b"), StubProvider())
        targets = reg.list_targets()
        assert len(targets) == 2
        assert targets[0].id == "t1"

    def test_remove(self) -> None:
        reg = TargetRegistry.get()
        reg.register("t1", TargetInfo(id="t1", name="A", provider_type="a"), StubProvider())
        reg.remove("t1")
        assert reg.get_provider("t1") is None
        assert reg.list_targets() == []

    def test_remove_default_falls_back(self) -> None:
        reg = TargetRegistry.get()
        reg.register("t1", TargetInfo(id="t1", name="A", provider_type="a"), StubProvider())
        reg.register("t2", TargetInfo(id="t2", name="B", provider_type="b"), StubProvider())
        assert reg.default_id == "t1"
        reg.remove("t1")
        assert reg.default_id == "t2"

    def test_remove_nonexistent(self) -> None:
        TargetRegistry.get().remove("nope")  # should not raise
