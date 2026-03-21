"""Tests for Spaces detection and switching."""

from __future__ import annotations

from unittest.mock import patch

from hort.spaces import SpaceInfo, get_current_space_index, get_space_count, get_spaces, switch_to_space

MOCK_DISPLAYS: list[dict[str, object]] = [
    {
        "Current Space": {"ManagedSpaceID": 3},
        "Spaces": [
            {"ManagedSpaceID": 3},
            {"ManagedSpaceID": 1031},
            {"ManagedSpaceID": 2048},
        ],
    }
]


class TestGetSpaces:
    def test_returns_spaces(self) -> None:
        with patch("hort.spaces._read_display_spaces", return_value=MOCK_DISPLAYS):
            spaces = get_spaces()
        assert len(spaces) == 3
        assert spaces[0] == SpaceInfo(index=1, space_id=3, is_current=True)
        assert spaces[1] == SpaceInfo(index=2, space_id=1031, is_current=False)
        assert spaces[2] == SpaceInfo(index=3, space_id=2048, is_current=False)

    def test_empty_displays(self) -> None:
        with patch("hort.spaces._read_display_spaces", return_value=[]):
            assert get_spaces() == []


class TestGetCurrentSpaceIndex:
    def test_returns_current(self) -> None:
        with patch("hort.spaces._read_display_spaces", return_value=MOCK_DISPLAYS):
            assert get_current_space_index() == 1

    def test_default_when_empty(self) -> None:
        with patch("hort.spaces._read_display_spaces", return_value=[]):
            assert get_current_space_index() == 1


class TestGetSpaceCount:
    def test_returns_count(self) -> None:
        with patch("hort.spaces._read_display_spaces", return_value=MOCK_DISPLAYS):
            assert get_space_count() == 3


class TestSwitchToSpace:
    def test_switch_right(self) -> None:
        with (
            patch("hort.spaces._read_display_spaces", return_value=MOCK_DISPLAYS),
            patch("hort.spaces._switch_space_keystroke") as mock_key,
            patch("hort.spaces._wait_for_space", return_value=True),
        ):
            result = switch_to_space(3)
        assert result is True
        assert mock_key.call_count == 2
        mock_key.assert_any_call("right")

    def test_switch_left(self) -> None:
        displays: list[dict[str, object]] = [
            {
                "Current Space": {"ManagedSpaceID": 2048},
                "Spaces": [
                    {"ManagedSpaceID": 3},
                    {"ManagedSpaceID": 1031},
                    {"ManagedSpaceID": 2048},
                ],
            }
        ]
        with (
            patch("hort.spaces._read_display_spaces", return_value=displays),
            patch("hort.spaces._switch_space_keystroke") as mock_key,
            patch("hort.spaces._wait_for_space", return_value=True),
        ):
            result = switch_to_space(1)
        assert result is True
        assert mock_key.call_count == 2
        mock_key.assert_any_call("left")

    def test_already_on_target(self) -> None:
        with patch("hort.spaces._read_display_spaces", return_value=MOCK_DISPLAYS):
            result = switch_to_space(1)
        assert result is True

    def test_out_of_range(self) -> None:
        with patch("hort.spaces._read_display_spaces", return_value=MOCK_DISPLAYS):
            assert switch_to_space(0) is False
            assert switch_to_space(5) is False
