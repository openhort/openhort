"""Tests for LaunchAgent autostart management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hort_statusbar import autostart


class TestAutostart:
    def test_plist_path(self) -> None:
        assert autostart.PLIST_PATH.name == "com.openhort.statusbar.plist"
        assert "LaunchAgents" in str(autostart.PLIST_PATH)

    def test_label(self) -> None:
        assert autostart.LABEL == "com.openhort.statusbar"

    def test_is_installed_false(self, tmp_path: Path) -> None:
        with patch.object(autostart, "PLIST_PATH", tmp_path / "nonexistent.plist"):
            assert not autostart.is_installed()

    def test_install_creates_plist(self, tmp_path: Path) -> None:
        plist = tmp_path / "com.openhort.statusbar.plist"
        with (
            patch.object(autostart, "PLIST_PATH", plist),
            patch("subprocess.run"),
        ):
            autostart.install()
        assert plist.exists()
        content = plist.read_text()
        assert "com.openhort.statusbar" in content
        assert "hort_statusbar" in content

    def test_uninstall_removes_plist(self, tmp_path: Path) -> None:
        plist = tmp_path / "com.openhort.statusbar.plist"
        plist.write_text("test")
        with (
            patch.object(autostart, "PLIST_PATH", plist),
            patch("subprocess.run"),
        ):
            autostart.uninstall()
        assert not plist.exists()

    def test_uninstall_nonexistent(self, tmp_path: Path) -> None:
        plist = tmp_path / "nonexistent.plist"
        with patch.object(autostart, "PLIST_PATH", plist):
            autostart.uninstall()  # should not raise
