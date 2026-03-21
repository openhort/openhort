"""Shared test fixtures."""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from hort.models import WindowBounds, WindowInfo


@pytest.fixture()
def sample_raw_windows() -> list[dict[str, Any]]:
    """Raw Quartz-style window dicts for testing."""
    return [
        {
            "kCGWindowNumber": 101,
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowName": "GitHub - Tab 1",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1200, "Height": 800},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 1001,
            "kCGWindowIsOnscreen": True,
        },
        {
            "kCGWindowNumber": 102,
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowName": "Stack Overflow",
            "kCGWindowBounds": {"X": 100, "Y": 100, "Width": 1000, "Height": 700},
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
        # Should be filtered: layer != 0
        {
            "kCGWindowNumber": 301,
            "kCGWindowOwnerName": "SystemUIServer",
            "kCGWindowName": "Menu Bar",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1920, "Height": 25},
            "kCGWindowLayer": 25,
            "kCGWindowOwnerPID": 3001,
            "kCGWindowIsOnscreen": True,
        },
        # Should be filtered: zero width
        {
            "kCGWindowNumber": 401,
            "kCGWindowOwnerName": "Dock",
            "kCGWindowName": "",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 0, "Height": 0},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 4001,
            "kCGWindowIsOnscreen": True,
        },
        # Should be filtered: no owner name
        {
            "kCGWindowNumber": 501,
            "kCGWindowOwnerName": "",
            "kCGWindowName": "orphan",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 5001,
            "kCGWindowIsOnscreen": True,
        },
    ]


@pytest.fixture()
def sample_window_info() -> list[WindowInfo]:
    """Parsed WindowInfo models (only the valid ones)."""
    return [
        WindowInfo(
            window_id=201,
            owner_name="Code",
            window_name="main.py — project",
            bounds=WindowBounds(x=50, y=50, width=1400, height=900),
            layer=0,
            owner_pid=2001,
            is_on_screen=True,
        ),
        WindowInfo(
            window_id=101,
            owner_name="Google Chrome",
            window_name="GitHub - Tab 1",
            bounds=WindowBounds(x=0, y=0, width=1200, height=800),
            layer=0,
            owner_pid=1001,
            is_on_screen=True,
        ),
        WindowInfo(
            window_id=102,
            owner_name="Google Chrome",
            window_name="Stack Overflow",
            bounds=WindowBounds(x=100, y=100, width=1000, height=700),
            layer=0,
            owner_pid=1001,
            is_on_screen=True,
        ),
    ]


@pytest.fixture()
def sample_jpeg_bytes() -> bytes:
    """A minimal valid JPEG image for testing."""
    img = Image.new("RGB", (200, 150), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


@pytest.fixture()
def app_client(sample_raw_windows: list[dict[str, Any]], sample_jpeg_bytes: bytes) -> TestClient:
    """FastAPI TestClient with mocked Quartz layer."""
    with (
        patch("hort.windows._raw_window_list", return_value=sample_raw_windows),
        patch("hort.windows._get_space_index_map", return_value={1: 1}),
        patch("hort.windows._get_window_space", return_value=1),
        patch("hort.app.capture_window", return_value=sample_jpeg_bytes),
    ):
        from hort.app import create_app

        test_app = create_app(dev_mode=False)
        with TestClient(test_app) as client:
            yield client  # type: ignore[misc]
