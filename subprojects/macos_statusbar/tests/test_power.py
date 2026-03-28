"""Tests for PowerManager."""

from __future__ import annotations

from unittest.mock import patch

from hort_statusbar.power import PowerManager


class TestPowerManager:
    def test_initial_state(self) -> None:
        pm = PowerManager()
        assert not pm.is_preventing_sleep
        assert not pm.is_preventing_display_sleep

    def test_allow_sleep_when_not_active(self) -> None:
        pm = PowerManager()
        pm.allow_sleep()  # should not raise
        assert not pm.is_preventing_sleep

    def test_prevent_sleep_without_iokit(self) -> None:
        pm = PowerManager()
        with patch("hort_statusbar.power.IOKit", None):
            result = pm.prevent_sleep()
        assert result is False

    def test_allow_sleep_without_iokit(self) -> None:
        pm = PowerManager()
        with patch("hort_statusbar.power.IOKit", None):
            pm.allow_sleep()  # should not raise
