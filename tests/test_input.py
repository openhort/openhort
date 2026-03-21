"""Tests for input simulation."""

from __future__ import annotations

from unittest.mock import patch

from hort.input import (
    KEYCODE_MAP,
    MODIFIER_FLAGS,
    _modifier_mask,
    _to_screen_coords,
    handle_input,
)
from hort.models import InputEvent, WindowBounds


class TestToScreenCoords:
    def test_origin(self) -> None:
        bounds = WindowBounds(x=100, y=200, width=800, height=600)
        sx, sy = _to_screen_coords(0.0, 0.0, bounds)
        assert sx == 100.0
        assert sy == 200.0

    def test_center(self) -> None:
        bounds = WindowBounds(x=100, y=200, width=800, height=600)
        sx, sy = _to_screen_coords(0.5, 0.5, bounds)
        assert sx == 500.0
        assert sy == 500.0

    def test_bottom_right(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=1920, height=1080)
        sx, sy = _to_screen_coords(1.0, 1.0, bounds)
        assert sx == 1920.0
        assert sy == 1080.0


class TestModifierMask:
    def test_empty(self) -> None:
        assert _modifier_mask([]) == 0

    def test_single(self) -> None:
        assert _modifier_mask(["shift"]) == MODIFIER_FLAGS["shift"]

    def test_multiple(self) -> None:
        mask = _modifier_mask(["shift", "cmd"])
        assert mask == MODIFIER_FLAGS["shift"] | MODIFIER_FLAGS["cmd"]

    def test_unknown_ignored(self) -> None:
        assert _modifier_mask(["unknown"]) == 0

    def test_case_insensitive(self) -> None:
        assert _modifier_mask(["Shift"]) == MODIFIER_FLAGS["shift"]


class TestHandleInput:
    def test_click(self) -> None:
        bounds = WindowBounds(x=100, y=200, width=800, height=600)
        event = InputEvent(type="click", nx=0.5, ny=0.5)
        with patch("hort.input._post_mouse") as mock:
            handle_input(event, bounds)
        # move + down + up = 3 calls
        assert mock.call_count == 3

    def test_click_with_pid_activates_app(self) -> None:
        """Clicks activate the target app so the window is in front."""
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="click", nx=0.5, ny=0.5)
        with (
            patch("hort.input._post_mouse"),
            patch("hort.input._activate_app") as mock_activate,
        ):
            handle_input(event, bounds, pid=1234)
        mock_activate.assert_called_once()
        assert mock_activate.call_args[0][0] == 1234
        assert mock_activate.call_args[1]["bounds"] is not None

    def test_click_no_pid_no_activate(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="click", nx=0.5, ny=0.5)
        with (
            patch("hort.input._post_mouse"),
            patch("hort.input._activate_app") as mock_activate,
        ):
            handle_input(event, bounds, pid=0)
        mock_activate.assert_not_called()

    def test_move_no_activate(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="move", nx=0.5, ny=0.5)
        with (
            patch("hort.input._post_mouse"),
            patch("hort.input._activate_app") as mock_activate,
        ):
            handle_input(event, bounds, pid=1234)
        mock_activate.assert_not_called()

    def test_double_click(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="double_click", nx=0.5, ny=0.5)
        with patch("hort.input._post_mouse") as mock:
            handle_input(event, bounds)
        # move + 2*(down + up) = 5 calls
        assert mock.call_count == 5

    def test_right_click(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="right_click", nx=0.5, ny=0.5)
        with patch("hort.input._post_mouse") as mock:
            handle_input(event, bounds)
        # move + down + up = 3 calls
        assert mock.call_count == 3

    def test_move(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="move", nx=0.5, ny=0.5)
        with patch("hort.input._post_mouse") as mock:
            handle_input(event, bounds)
        assert mock.call_count == 1

    def test_scroll(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="scroll", nx=0.5, ny=0.5, dx=0, dy=-3)
        with patch("hort.input._post_scroll") as mock:
            handle_input(event, bounds)
        mock.assert_called_once_with(50.0, 50.0, 0, -3)

    def test_key_special(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="key", key="Return")
        with patch("hort.input._post_key") as mock:
            handle_input(event, bounds)
        assert mock.call_count == 2  # down + up
        mock.assert_any_call(KEYCODE_MAP["Return"], True, 0)
        mock.assert_any_call(KEYCODE_MAP["Return"], False, 0)

    def test_key_with_pid_activates_app(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="key", key="a")
        with (
            patch("hort.input._post_key_char"),
            patch("hort.input._activate_app") as mock_activate,
        ):
            handle_input(event, bounds, pid=999)
        mock_activate.assert_called_once()
        assert mock_activate.call_args[0][0] == 999

    def test_key_no_pid_no_activate(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="key", key="a")
        with (
            patch("hort.input._post_key_char"),
            patch("hort.input._activate_app") as mock_activate,
        ):
            handle_input(event, bounds, pid=0)
        mock_activate.assert_not_called()

    def test_key_char(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="key", key="a")
        with patch("hort.input._post_key_char") as mock:
            handle_input(event, bounds)
        mock.assert_called_once_with("a", 0)

    def test_key_with_modifiers(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="key", key="a", modifiers=["cmd"])
        with patch("hort.input._post_key_char") as mock:
            handle_input(event, bounds)
        mock.assert_called_once_with("a", MODIFIER_FLAGS["cmd"])

    def test_unknown_type_noop(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        event = InputEvent(type="unknown", nx=0.5, ny=0.5)
        with (
            patch("hort.input._post_mouse") as mock_mouse,
            patch("hort.input._post_key") as mock_key,
        ):
            handle_input(event, bounds)
        mock_mouse.assert_not_called()
        mock_key.assert_not_called()

    def test_click_coordinates(self) -> None:
        bounds = WindowBounds(x=100, y=200, width=800, height=600)
        event = InputEvent(type="click", nx=0.25, ny=0.75)
        with patch("hort.input._post_mouse") as mock:
            handle_input(event, bounds)
        # Check the move call coordinates (first call)
        args = mock.call_args_list[0][0]
        assert args[1] == 300.0  # 100 + 0.25*800
        assert args[2] == 650.0  # 200 + 0.75*600
