"""Tests for window listing and filtering."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from hort.models import WindowInfo
from hort.windows import _parse_window, get_app_names, list_windows

# Shared mock context for list_windows tests (need space mocks)
_SPACE_MOCKS = {
    "hort.windows._get_space_index_map": {1: 1},
    "hort.windows._get_window_space": 1,
}


def _patch_windows(raw: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    """Context manager that mocks raw window list + space lookups."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("hort.windows._raw_window_list", return_value=raw))
    stack.enter_context(patch("hort.windows._get_space_index_map", return_value={1: 1}))
    stack.enter_context(patch("hort.windows._get_window_space", return_value=1))
    return stack


class TestParseWindow:
    def test_valid_window(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 42,
            "kCGWindowOwnerName": "Chrome",
            "kCGWindowName": "Tab 1",
            "kCGWindowBounds": {"X": 10, "Y": 20, "Width": 800, "Height": 600},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 123,
            "kCGWindowIsOnscreen": True,
        }
        win = _parse_window(raw)
        assert win is not None
        assert win.window_id == 42
        assert win.owner_name == "Chrome"
        assert win.window_name == "Tab 1"
        assert win.bounds.width == 800
        assert win.bounds.height == 600

    def test_missing_owner_name(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
            "kCGWindowLayer": 0,
        }
        assert _parse_window(raw) is None

    def test_no_owner_key(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
            "kCGWindowLayer": 0,
        }
        assert _parse_window(raw) is None

    def test_zero_area(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "App",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 0, "Height": 100},
            "kCGWindowLayer": 0,
        }
        assert _parse_window(raw) is None

    def test_non_zero_layer(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "MenuBar",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1920, "Height": 25},
            "kCGWindowLayer": 25,
        }
        assert _parse_window(raw) is None

    def test_missing_bounds(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "App",
            "kCGWindowLayer": 0,
        }
        assert _parse_window(raw) is None

    def test_missing_window_name(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "App",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
            "kCGWindowLayer": 0,
        }
        assert _parse_window(raw) is None

    def test_none_window_name(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "App",
            "kCGWindowName": None,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
            "kCGWindowLayer": 0,
        }
        assert _parse_window(raw) is None

    def test_negative_height(self) -> None:
        raw: dict[str, Any] = {
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "App",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": -10},
            "kCGWindowLayer": 0,
        }
        assert _parse_window(raw) is None


class TestListWindows:
    def test_returns_valid_windows(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        with _patch_windows(sample_raw_windows):
            windows = list_windows()
        assert len(windows) == 3
        assert all(isinstance(w, WindowInfo) for w in windows)

    def test_sorted_by_name(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        with _patch_windows(sample_raw_windows):
            windows = list_windows()
        names = [w.owner_name for w in windows]
        assert names == ["Code", "Google Chrome", "Google Chrome"]

    def test_filter_by_app(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        with _patch_windows(sample_raw_windows):
            windows = list_windows(app_filter="Chrome")
        assert len(windows) == 2
        assert all(w.owner_name == "Google Chrome" for w in windows)

    def test_filter_case_insensitive(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        with _patch_windows(sample_raw_windows):
            windows = list_windows(app_filter="chrome")
        assert len(windows) == 2

    def test_filter_no_match(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        with _patch_windows(sample_raw_windows):
            windows = list_windows(app_filter="Nonexistent")
        assert len(windows) == 0

    def test_empty_list(self) -> None:
        with _patch_windows([]):
            windows = list_windows()
        assert windows == []

    def test_filter_none_returns_all(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        with _patch_windows(sample_raw_windows):
            windows = list_windows(app_filter=None)
        assert len(windows) == 3

    def test_filters_out_unknown_space(self) -> None:
        raw: list[dict[str, Any]] = [{
            "kCGWindowNumber": 1,
            "kCGWindowOwnerName": "App",
            "kCGWindowName": "Window",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 1,
            "kCGWindowIsOnscreen": True,
        }]
        with (
            patch("hort.windows._raw_window_list", return_value=raw),
            patch("hort.windows._get_space_index_map", return_value={}),
            patch("hort.windows._get_window_space", return_value=0),
        ):
            windows = list_windows()
        assert len(windows) == 0


class TestGetAppNames:
    def test_returns_sorted_unique(
        self, sample_raw_windows: list[dict[str, Any]]
    ) -> None:
        with _patch_windows(sample_raw_windows):
            names = get_app_names()
        assert names == ["Code", "Google Chrome"]

    def test_empty(self) -> None:
        with _patch_windows([]):
            names = get_app_names()
        assert names == []
