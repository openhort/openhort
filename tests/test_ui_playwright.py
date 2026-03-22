"""Playwright UI tests — render and screenshot the openhort viewer.

These tests start a real server, open the UI in a headless Chromium browser,
and verify that the Quasar app renders correctly.

Run with::

    pytest tests/test_ui_playwright.py -v

Screenshots are saved to ``screenshots/`` for visual inspection.

Requires:
    poetry add --group dev playwright pytest-playwright
    poetry run playwright install chromium
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest
import uvicorn

SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# Mark all tests in this module as integration (skipped by default)
pytestmark = pytest.mark.integration


# ===== Fixtures =====


def _sample_raw_windows() -> list[dict[str, Any]]:
    """Fake window data for testing."""
    return [
        {
            "kCGWindowNumber": 101,
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowName": "GitHub - openhort",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1200, "Height": 800},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 1001,
            "kCGWindowIsOnscreen": True,
        },
        {
            "kCGWindowNumber": 201,
            "kCGWindowOwnerName": "Code",
            "kCGWindowName": "main.py — project",
            "kCGWindowBounds": {"X": 50, "Y": 50, "Width": 1400, "Height": 900},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 2001,
            "kCGWindowIsOnscreen": True,
        },
        {
            "kCGWindowNumber": 301,
            "kCGWindowOwnerName": "iTerm2",
            "kCGWindowName": "~/projects",
            "kCGWindowBounds": {"X": 100, "Y": 100, "Width": 1000, "Height": 600},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 3001,
            "kCGWindowIsOnscreen": True,
        },
    ]


def _fake_jpeg() -> bytes:
    """Generate a small valid JPEG for thumbnail responses."""
    from PIL import Image
    import io

    img = Image.new("RGB", (200, 150), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=50)
    return buf.getvalue()


@pytest.fixture(scope="module")
def server_url() -> Generator[str, None, None]:
    """Start a real openhort server on a random port with mocked capture."""
    import socket

    # Find a free port
    with socket.socket() as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    jpeg = _fake_jpeg()

    with (
        patch("hort.windows._raw_window_list", return_value=_sample_raw_windows()),
        patch("hort.windows._get_space_index_map", return_value={1: 1}),
        patch("hort.windows._get_window_space", return_value=1),
        patch("hort.screen._raw_capture", return_value=None),
        patch("hort.controller.capture_window", return_value=jpeg),
        patch("hort.stream.capture_window", return_value=jpeg),
        patch("hort.stream._raise_window"),
        patch("hort.spaces._read_display_spaces", return_value=[]),
    ):
        from hort.app import create_app

        app = create_app(dev_mode=False)

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)

        loop = asyncio.new_event_loop()
        thread_import = __import__("threading")
        thread = thread_import.Thread(target=loop.run_until_complete, args=(server.serve(),), daemon=True)
        thread.start()

        # Wait for server to be ready
        for _ in range(50):
            try:
                import httpx
                httpx.get(f"http://127.0.0.1:{port}/api/hash", timeout=1.0)
                break
            except Exception:
                time.sleep(0.1)

        yield f"http://127.0.0.1:{port}"

        server.should_exit = True
        thread.join(timeout=5)


# ===== Tests =====


class TestViewerRenders:
    """Verify the Quasar UI renders in a real browser."""

    def test_landing_page(self, server_url: str, page: Any) -> None:
        """Landing page shows QR code and link."""
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")

        assert "openhort" in page.title() or "hort" in page.title()
        assert page.locator("h1").inner_text() == "openhort"
        assert page.locator("img[alt='QR Code']").is_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / "landing.png"), full_page=True)

    def test_viewer_loads_quasar(self, server_url: str, page: Any) -> None:
        """Viewer page loads Vue + Quasar without errors."""
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        page.goto(f"{server_url}/viewer")
        page.wait_for_load_state("networkidle")

        # Quasar should be loaded
        quasar_loaded = page.evaluate("typeof Quasar !== 'undefined' && !!Quasar.version")
        assert quasar_loaded, "Quasar did not load"

        vue_mounted = page.evaluate("!!document.querySelector('#q-app').__vue_app__")
        assert vue_mounted, "Vue app did not mount"

        assert not errors, f"JS errors on page: {errors}"

        page.screenshot(path=str(SCREENSHOTS_DIR / "viewer_init.png"), full_page=True)

    def test_picker_shows_windows(self, server_url: str, page: Any) -> None:
        """Picker view lists windows from the mocked window data."""
        page.goto(f"{server_url}/viewer")
        page.wait_for_load_state("networkidle")

        # Wait for windows to load via control WS
        page.wait_for_timeout(2000)

        # Should see the app filter dropdown
        app_filter = page.locator("select").first
        assert app_filter.is_visible()

        # Should see window cards
        cards = page.locator(".win-card")
        count = cards.count()
        assert count >= 1, f"Expected window cards, got {count}"

        page.screenshot(path=str(SCREENSHOTS_DIR / "picker.png"), full_page=True)

    def test_viewer_streams(self, server_url: str, page: Any) -> None:
        """Clicking a window card enters the viewer and starts streaming."""
        page.goto(f"{server_url}/viewer")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Click the first window card
        first_card = page.locator(".win-card").first
        if first_card.is_visible():
            first_card.click()
            page.wait_for_timeout(2000)

            page.screenshot(path=str(SCREENSHOTS_DIR / "viewer_streaming.png"), full_page=True)

    def test_no_broken_images(self, server_url: str, page: Any) -> None:
        """No visible thumbnail images should have empty src or show error icons."""
        page.goto(f"{server_url}/viewer")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Only check images that are actually visible (picker thumbnails),
        # not the hidden stream/minimap imgs which have no src until streaming
        broken = page.evaluate("""
            (() => {
                const imgs = document.querySelectorAll('.win-thumb, .overview-card img, .strip-item img');
                let bad = 0;
                imgs.forEach(img => {
                    if (img.src === '' || img.src === location.href) bad++;
                });
                return bad;
            })()
        """)
        assert broken == 0, f"{broken} thumbnail images have empty/self-referencing src"

        page.screenshot(path=str(SCREENSHOTS_DIR / "no_broken_images.png"), full_page=True)

    def test_mobile_viewport(self, server_url: str, browser: Any) -> None:
        """Viewer renders correctly at mobile viewport size."""
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
        )
        mobile_page = context.new_page()
        mobile_page.goto(f"{server_url}/viewer")
        mobile_page.wait_for_load_state("networkidle")
        mobile_page.wait_for_timeout(2000)

        mobile_page.screenshot(path=str(SCREENSHOTS_DIR / "mobile_picker.png"), full_page=True)

        # Click first card if visible
        first_card = mobile_page.locator(".win-card").first
        if first_card.is_visible():
            first_card.click()
            mobile_page.wait_for_timeout(2000)
            mobile_page.screenshot(path=str(SCREENSHOTS_DIR / "mobile_viewer.png"), full_page=True)

        context.close()

    def test_tablet_viewport(self, server_url: str, browser: Any) -> None:
        """Viewer renders correctly at tablet viewport size."""
        context = browser.new_context(
            viewport={"width": 1024, "height": 768},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        tablet_page = context.new_page()
        tablet_page.goto(f"{server_url}/viewer")
        tablet_page.wait_for_load_state("networkidle")
        tablet_page.wait_for_timeout(2000)

        tablet_page.screenshot(path=str(SCREENSHOTS_DIR / "tablet_picker.png"), full_page=True)
        context.close()
