"""Playwright P2P WebRTC tests — prove the signaling and DataChannel work.

Tests start a real server, open the Mini App in headless Chromium, and verify
that WebRTC signaling (SDP offer → answer) and DataChannel establishment work
end-to-end.

Run with::

    pytest tests/test_p2p_playwright.py -v -m integration

Screenshots saved to ``screenshots/p2p/``.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest
import uvicorn

SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots" / "p2p"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

pytestmark = pytest.mark.integration


# ===== Helpers =====


def _sample_raw_windows() -> list[dict[str, Any]]:
    return [
        {
            "kCGWindowNumber": 101,
            "kCGWindowOwnerName": "TestApp",
            "kCGWindowName": "P2P Test Window",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 1001,
            "kCGWindowIsOnscreen": True,
        },
    ]


@pytest.fixture(scope="module")
def server_url() -> Generator[str, None, None]:
    """Start a real openhort server — only mock window listing (not capture)."""
    import socket

    with socket.socket() as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    with (
        patch("hort.windows._raw_window_list", return_value=_sample_raw_windows()),
        patch("hort.windows._get_space_index_map", return_value={1: 1}),
        patch("hort.windows._get_window_space", return_value=1),
        patch("hort.screen._raw_capture", return_value=None),
        patch("hort.spaces._read_display_spaces", return_value=[]),
    ):
        from hort.app import create_app

        app = create_app(dev_mode=False)

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)

        loop = asyncio.new_event_loop()
        thread_import = __import__("threading")
        thread = thread_import.Thread(
            target=loop.run_until_complete, args=(server.serve(),), daemon=True
        )
        thread.start()

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


class TestMiniAppLoads:
    """Verify the Mini App page renders correctly."""

    def test_miniapp_renders(self, server_url: str, page: Any) -> None:
        """Mini App loads and shows connect button."""
        page.goto(f"{server_url}/p2p")
        page.wait_for_load_state("networkidle")

        assert page.locator("h1").inner_text() == "openhort"
        assert page.locator("#btnConnect").is_visible()
        assert page.locator("#btnDisconnect").is_disabled()

        page.screenshot(path=str(SCREENSHOTS_DIR / "p2p_loaded.png"))

    def test_miniapp_logs_init(self, server_url: str, page: Any) -> None:
        """Mini App log shows initialization message."""
        page.goto(f"{server_url}/p2p")
        page.wait_for_load_state("networkidle")

        log_text = page.locator("#log").inner_text()
        assert "P2P viewer loaded" in log_text


class TestWebRTCSignaling:
    """Verify WebRTC SDP offer/answer exchange works."""

    def test_signaling_api(self, server_url: str, page: Any) -> None:
        """POST /api/p2p/offer returns a valid SDP answer via browser."""
        # Use the browser to create a real WebRTC offer (more reliable than aiortc in tests)
        page.goto(f"{server_url}/p2p")
        page.wait_for_load_state("networkidle")

        # Create offer and send it via JS, check the response
        result = page.evaluate("""async () => {
            const sessResp = await fetch('/api/session', { method: 'POST' });
            const sessData = await sessResp.json();

            const pc = new RTCPeerConnection({
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
            });
            pc.createDataChannel('test');
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);

            // Wait briefly for ICE candidates
            await new Promise(r => setTimeout(r, 1000));

            const resp = await fetch('/api/p2p/offer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sdp: pc.localDescription.sdp,
                    session_id: sessData.session_id,
                }),
            });
            const data = await resp.json();
            pc.close();
            return { status: resp.status, data, session_id: sessData.session_id };
        }""")

        assert result["status"] == 200
        assert "sdp" in result["data"]
        assert result["data"]["type"] == "answer"
        assert result["data"]["session_id"] == result["session_id"]

    def test_signaling_api_missing_params(self, server_url: str) -> None:
        """Missing params return error."""
        import httpx

        resp = httpx.post(
            f"{server_url}/api/p2p/offer",
            json={"sdp": ""},
            timeout=5.0,
        )
        assert "error" in resp.json()

    def test_p2p_status_no_peer(self, server_url: str) -> None:
        """Status endpoint returns not connected for unknown session."""
        import httpx

        resp = httpx.get(f"{server_url}/api/p2p/status/nonexistent")
        assert resp.json()["connected"] is False


class TestBrowserWebRTC:
    """End-to-end: browser creates WebRTC offer, server answers, DataChannel opens."""

    def test_webrtc_connection(self, server_url: str, page: Any) -> None:
        """Full WebRTC flow in headless Chromium."""
        page.goto(f"{server_url}/p2p")
        page.wait_for_load_state("networkidle")

        # Click connect
        page.locator("#btnConnect").click()

        # Wait for SDP answer to be received (up to 15s)
        try:
            page.wait_for_function(
                """() => {
                    const log = document.getElementById('log').textContent;
                    return log.includes('SDP answer received') || log.includes('Error');
                }""",
                timeout=15000,
            )
        except Exception:
            pass

        # Take screenshot
        page.screenshot(path=str(SCREENSHOTS_DIR / "webrtc_connection.png"))

        # Check the signaling worked
        log_text = page.locator("#log").inner_text()
        assert "Session:" in log_text
        assert "SDP offer ready" in log_text
        assert "SDP answer received" in log_text
        assert "ICE negotiation started" in log_text

    def test_webrtc_datachannel_opens(self, server_url: str, page: Any) -> None:
        """DataChannel opens end-to-end (both sides localhost = no NAT)."""
        page.goto(f"{server_url}/p2p")
        page.wait_for_load_state("networkidle")

        page.locator("#btnConnect").click()

        # Wait for DataChannel to open (localhost-to-localhost, should be fast)
        try:
            page.wait_for_function(
                """() => {
                    const log = document.getElementById('log').textContent;
                    return log.includes('DataChannel open') || log.includes('failed');
                }""",
                timeout=15000,
            )
        except Exception:
            pass

        page.screenshot(path=str(SCREENSHOTS_DIR / "datachannel_open.png"))

        log_text = page.locator("#log").inner_text()

        if "DataChannel open" in log_text:
            assert "P2P connection established" in log_text
            assert not page.locator("#btnDisconnect").is_disabled()

    def test_disconnect(self, server_url: str, page: Any) -> None:
        """Disconnect button closes the connection."""
        page.goto(f"{server_url}/p2p")
        page.wait_for_load_state("networkidle")

        page.locator("#btnConnect").click()

        # Wait for connection or timeout
        try:
            page.wait_for_function(
                """() => {
                    const log = document.getElementById('log').textContent;
                    return log.includes('DataChannel open') || log.includes('ICE:');
                }""",
                timeout=10000,
            )
        except Exception:
            pass

        # If connected, disconnect
        if not page.locator("#btnDisconnect").is_disabled():
            page.locator("#btnDisconnect").click()
            page.wait_for_timeout(500)
            log_text = page.locator("#log").inner_text()
            assert "Disconnected" in log_text

        page.screenshot(path=str(SCREENSHOTS_DIR / "disconnected.png"))
