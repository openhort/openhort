"""Integration tests that run against the real macOS APIs.

These tests require:
- Screen Recording permission
- Accessibility permission
- Real windows to be open

Run with: pytest tests/test_integration.py -v
Normal test runs skip these: pytest tests/ -m "not integration"
"""

from __future__ import annotations

import subprocess
import time

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestWindowListing:
    def test_lists_real_windows(self) -> None:
        from hort.windows import list_windows

        windows = list_windows()
        assert len(windows) > 0
        for w in windows:
            assert w.window_id > 0
            assert w.owner_name
            assert w.bounds.width > 0
            assert w.bounds.height > 0

    def test_filter_by_app(self) -> None:
        from hort.windows import list_windows

        all_windows = list_windows()
        app_name = all_windows[0].owner_name
        filtered = list_windows(app_filter=app_name)
        assert len(filtered) >= 1
        assert all(w.owner_name == app_name for w in filtered)

    def test_get_app_names(self) -> None:
        from hort.windows import get_app_names

        names = get_app_names()
        assert len(names) > 0
        assert names == sorted(names)


class TestScreenCapture:
    def test_capture_real_window(self) -> None:
        from hort.screen import capture_window
        from hort.windows import list_windows

        windows = list_windows()
        jpeg = capture_window(windows[0].window_id)
        assert jpeg is not None
        assert jpeg[:2] == b"\xff\xd8"  # JPEG magic
        assert len(jpeg) > 100

    def test_capture_nonexistent_window(self) -> None:
        from hort.screen import capture_window

        result = capture_window(999999999)
        assert result is None

    def test_capture_respects_max_width(self) -> None:
        from hort.screen import capture_window
        from hort.windows import list_windows

        from PIL import Image
        import io

        windows = list_windows()
        jpeg = capture_window(windows[0].window_id, max_width=200)
        assert jpeg is not None
        img = Image.open(io.BytesIO(jpeg))
        assert img.width <= 200

    def test_capture_quality_affects_size(self) -> None:
        from hort.screen import capture_window
        from hort.windows import list_windows

        windows = list_windows()
        wid = windows[0].window_id
        low = capture_window(wid, quality=10)
        high = capture_window(wid, quality=95)
        assert low is not None and high is not None
        assert len(low) < len(high)


class TestNetworkAndCert:
    def test_lan_ip_is_real(self) -> None:
        from hort.network import get_lan_ip

        ip = get_lan_ip()
        assert ip != "127.0.0.1"  # should be a real LAN IP
        parts = ip.split(".")
        assert len(parts) == 4

    def test_qr_code_generation(self) -> None:
        from hort.network import generate_qr_data_uri

        uri = generate_qr_data_uri("https://192.168.1.1:8950")
        assert uri.startswith("data:image/png;base64,")
        assert len(uri) > 100

    def test_cert_generation(self, tmp_path: pytest.TempPathFactory) -> None:
        from hort.cert import ensure_certs

        cert_dir = tmp_path / "test_certs"  # type: ignore[operator]
        cert_path, key_path = ensure_certs(cert_dir, lan_ip="127.0.0.1")
        assert cert_path.exists()
        assert key_path.exists()
        assert cert_path.stat().st_size > 0


class TestActivateApp:
    def test_activate_real_app(self) -> None:
        """Test that _activate_app brings an app to front."""
        from hort.windows import list_windows

        windows = list_windows()
        if len(windows) < 2:
            pytest.skip("Need at least 2 windows")

        # Find two different apps
        apps = {}
        for w in windows:
            if w.owner_name not in apps:
                apps[w.owner_name] = w.owner_pid
            if len(apps) >= 2:
                break

        if len(apps) < 2:
            pytest.skip("Need at least 2 different apps")

        pids = list(apps.values())
        names = list(apps.keys())

        from hort.input import _activate_app

        # Activate second app
        _activate_app(pids[1])
        time.sleep(0.5)

        # Verify it's frontmost via AppleScript
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
        )
        frontmost = result.stdout.strip()
        # The frontmost app should be the one we activated
        assert frontmost == names[1], f"Expected {names[1]}, got {frontmost}"


class TestRaiseOnSwitch:
    def test_raise_window_for_config(self) -> None:
        """Test that switching config raises the window's app."""
        from hort.app import _raise_window_for_config
        from hort.models import StreamConfig
        from hort.windows import list_windows

        windows = list_windows()
        if len(windows) < 2:
            pytest.skip("Need at least 2 windows")

        # Find two different apps
        diff_app_windows = []
        seen_apps: set[str] = set()
        for w in windows:
            if w.owner_name not in seen_apps:
                diff_app_windows.append(w)
                seen_apps.add(w.owner_name)
            if len(diff_app_windows) >= 2:
                break

        if len(diff_app_windows) < 2:
            pytest.skip("Need at least 2 different apps")

        target = diff_app_windows[1]
        config = StreamConfig(window_id=target.window_id)
        _raise_window_for_config(config)
        time.sleep(0.5)

        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
        )
        frontmost = result.stdout.strip()
        assert frontmost == target.owner_name, (
            f"Expected {target.owner_name}, got {frontmost}"
        )
