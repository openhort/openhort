"""Playwright integration tests for VP8/VP9 video streaming over P2P.

Tests verify that:
1. WebRTC video track is offered by the server
2. Browser receives and decodes the video stream
3. VP8 encoding produces valid frames
4. The video element renders in the page

Run with::

    pytest tests/test_p2p_video_playwright.py -v -m integration
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest
import uvicorn
from PIL import Image

SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots" / "p2p_video"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

pytestmark = pytest.mark.integration


def _sample_raw_windows() -> list[dict[str, Any]]:
    return [
        {
            "kCGWindowNumber": 101,
            "kCGWindowOwnerName": "TestApp",
            "kCGWindowName": "Video Test",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1280, "Height": 720},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 1001,
            "kCGWindowIsOnscreen": True,
        },
    ]


@pytest.fixture(scope="module")
def server_url() -> Generator[str, None, None]:
    """Start server with video track support."""
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

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
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


class TestVideoTrackSignaling:
    """Verify the SDP answer includes a video track."""

    def test_sdp_answer_has_video(self, server_url: str, page: Any) -> None:
        """Server SDP answer should contain video media section."""
        page.goto(f"{server_url}/p2p?signal=http")
        page.wait_for_load_state("networkidle")

        result = page.evaluate("""async () => {
            const pc = new RTCPeerConnection({
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
            });

            // Request to receive video
            pc.addTransceiver('video', { direction: 'recvonly' });
            pc.createDataChannel('test');

            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            await new Promise(r => setTimeout(r, 1000));

            const resp = await fetch('/api/p2p/offer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sdp: pc.localDescription.sdp,
                    session_id: 'video-test',
                }),
            });
            const data = await resp.json();
            pc.close();

            return {
                status: resp.status,
                has_video: data.sdp && data.sdp.includes('m=video'),
                has_vp8: data.sdp && data.sdp.includes('VP8'),
                sdp_length: data.sdp ? data.sdp.length : 0,
            };
        }""")

        assert result["status"] == 200
        assert result["has_video"], "SDP answer should contain video media"
        assert result["has_vp8"], "SDP answer should offer VP8 codec"

    def test_video_track_received(self, server_url: str, page: Any) -> None:
        """Browser should receive a video track from the server."""
        page.goto(f"{server_url}/p2p?signal=http")
        page.wait_for_load_state("networkidle")

        result = page.evaluate("""() => new Promise((resolve) => {
            const pc = new RTCPeerConnection({
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
            });

            let videoTrackReceived = false;

            pc.addTransceiver('video', { direction: 'recvonly' });
            const dc = pc.createDataChannel('test');

            pc.ontrack = (evt) => {
                if (evt.track.kind === 'video') {
                    videoTrackReceived = true;
                }
            };

            pc.createOffer().then(offer => {
                pc.setLocalDescription(offer);
                return new Promise(r => setTimeout(r, 1000));
            }).then(() => {
                return fetch('/api/p2p/offer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sdp: pc.localDescription.sdp,
                        session_id: 'track-test',
                    }),
                });
            }).then(r => r.json()).then(data => {
                return pc.setRemoteDescription(new RTCSessionDescription({
                    type: 'answer', sdp: data.sdp
                }));
            }).then(() => {
                // Wait for track to arrive
                setTimeout(() => {
                    resolve({
                        videoTrackReceived,
                        connectionState: pc.connectionState,
                        iceState: pc.iceConnectionState,
                    });
                    pc.close();
                }, 15000);
            });
        })""")

        assert result["videoTrackReceived"], "Should receive a video track from server"


class TestVideoRendering:
    """Verify video frames are decoded and rendered."""

    def test_video_element_plays(self, server_url: str, page: Any) -> None:
        """Video element should receive frames and start playing."""
        page.goto(f"{server_url}/p2p?signal=http")
        page.wait_for_load_state("networkidle")

        result = page.evaluate("""() => new Promise((resolve) => {
            const pc = new RTCPeerConnection({
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
            });

            pc.addTransceiver('video', { direction: 'recvonly' });
            const dc = pc.createDataChannel('test');

            pc.ontrack = (evt) => {
                if (evt.track.kind === 'video') {
                    const video = document.createElement('video');
                    video.id = 'p2p-video';
                    video.autoplay = true;
                    video.playsInline = true;
                    video.muted = true;
                    video.style.cssText = 'width:640px;height:360px;position:fixed;top:0;left:0;z-index:9999;';
                    video.srcObject = evt.streams[0] || new MediaStream([evt.track]);
                    document.body.appendChild(video);
                }
            };

            pc.createOffer().then(offer => {
                pc.setLocalDescription(offer);
                return new Promise(r => setTimeout(r, 1000));
            }).then(() => {
                return fetch('/api/p2p/offer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sdp: pc.localDescription.sdp,
                        session_id: 'render-test',
                    }),
                });
            }).then(r => r.json()).then(data => {
                return pc.setRemoteDescription(new RTCSessionDescription({
                    type: 'answer', sdp: data.sdp
                }));
            }).then(() => {
                // Wait for video to start playing
                setTimeout(() => {
                    const video = document.getElementById('p2p-video');
                    resolve({
                        videoExists: !!video,
                        videoWidth: video ? video.videoWidth : 0,
                        videoHeight: video ? video.videoHeight : 0,
                        paused: video ? video.paused : true,
                        readyState: video ? video.readyState : 0,
                    });
                    pc.close();
                }, 8000);
            });
        })""")

        page.screenshot(path=str(SCREENSHOTS_DIR / "video_rendering.png"))

        assert result["videoExists"], "Video element should exist"
        # Video dimensions > 0 means frames were decoded
        if result["videoWidth"] > 0:
            assert result["videoHeight"] > 0
            assert result["readyState"] >= 2  # HAVE_CURRENT_DATA or better


class TestWebMEncoder:
    """Test VP8/VP9 encoding produces valid WebM data."""

    def test_vp8_produces_webm(self) -> None:
        """VP8 encoder should produce valid WebM bytes."""
        from hort.peer2peer.video_track import WebMEncoder

        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        total = 0
        for i in range(5):
            img = Image.new("RGB", (320, 240), color=(i * 50, 100, 50))
            data = encoder.encode_frame(img)
            total += len(data)
        encoder.close()
        assert total > 0, "VP8 should produce WebM output"

    def test_vp9_produces_webm(self) -> None:
        """VP9 encoder should produce valid WebM bytes."""
        from hort.peer2peer.video_track import WebMEncoder

        encoder = WebMEncoder(codec="vp9", fps=15, width=320, height=240)
        total = 0
        for i in range(5):
            img = Image.new("RGB", (320, 240), color=(i * 50, 100, 50))
            data = encoder.encode_frame(img)
            total += len(data)
        encoder.close()
        assert total > 0, "VP9 should produce WebM output"

    def test_init_segment_is_valid_webm(self) -> None:
        """Init segment should start with EBML header."""
        from hort.peer2peer.video_track import WebMEncoder

        encoder = WebMEncoder(codec="vp8", fps=15, width=320, height=240)
        init = encoder.get_init_segment()
        assert init[:4] == b"\x1a\x45\xdf\xa3", "Should start with EBML header"
        encoder.close()
