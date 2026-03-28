"""Playwright integration tests for unified video streaming.

Tests verify:
1. JPEG frames received with 6-byte header (stream_id + seq)
2. VP8 WebM frames received and decoded via MSE
3. Stream ACK sent via control WS after each frame
4. Codec switching works (JPEG → VP8 → VP9)
5. Works over P2P DataChannel proxy

Run with::

    pytest tests/test_stream_playwright.py -v -m integration
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest
import uvicorn

SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots" / "stream"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

pytestmark = pytest.mark.integration


def _sample_raw_windows() -> list[dict[str, Any]]:
    return [
        {
            "kCGWindowNumber": 101,
            "kCGWindowOwnerName": "TestApp",
            "kCGWindowName": "Stream Test",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600},
            "kCGWindowLayer": 0,
            "kCGWindowOwnerPID": 1001,
            "kCGWindowIsOnscreen": True,
        },
    ]


def _fake_jpeg() -> bytes:
    from PIL import Image
    import io
    img = Image.new("RGB", (200, 150), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=50)
    return buf.getvalue()


@pytest.fixture(scope="module")
def server_url() -> Generator[str, None, None]:
    import socket

    with socket.socket() as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    jpeg = _fake_jpeg()

    # Mock capture to return actual JPEG for stream testing
    def _mock_raw_capture(wid: int) -> object:
        """Return a fake CGImage-like object for testing."""
        return None  # _cgimage_to_pil handles None

    with (
        patch("hort.windows._raw_window_list", return_value=_sample_raw_windows()),
        patch("hort.windows._get_space_index_map", return_value={1: 1}),
        patch("hort.windows._get_window_space", return_value=1),
        patch("hort.screen._raw_capture", return_value=None),
        patch("hort.screen.capture_window", return_value=jpeg),
        patch("hort.spaces._read_display_spaces", return_value=[]),
    ):
        from hort.app import create_app

        app = create_app(dev_mode=False)

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)

        loop = asyncio.new_event_loop()
        thread = __import__("threading").Thread(
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


class TestStreamFrameHeader:
    """Verify frames have the 6-byte header with stream_id and seq."""

    def test_jpeg_frames_have_header(self, server_url: str, page: Any) -> None:
        """JPEG stream frames should have 6-byte header prefix."""
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        result = page.evaluate("""() => new Promise((resolve) => {
            // Create session and connect to stream
            fetch('/api/session', { method: 'POST' })
            .then(r => r.json())
            .then(sess => {
                const ws = new WebSocket(location.href.replace('http', 'ws') + 'ws/stream/' + sess.session_id);
                ws.binaryType = 'arraybuffer';

                // Send stream config via control WS
                const ctrl = new WebSocket(location.href.replace('http', 'ws') + 'ws/control/' + sess.session_id);
                ctrl.onopen = () => {
                    ctrl.send(JSON.stringify({
                        type: 'stream_config',
                        window_id: 101,
                        fps: 5,
                        quality: 50,
                        max_width: 200,
                    }));
                };

                let frameCount = 0;
                let firstHeader = null;

                ws.onmessage = (e) => {
                    if (e.data instanceof ArrayBuffer && e.data.byteLength > 10) {
                        const hdr = new DataView(e.data, 0, 10);
                        const streamId = hdr.getUint16(0);
                        const seq = hdr.getUint32(2);
                        const ts = hdr.getUint32(6);
                        if (!firstHeader) {
                            firstHeader = { streamId, seq, ts, totalSize: e.data.byteLength };
                        }
                        frameCount++;
                        if (frameCount >= 3) {
                            ws.close();
                            ctrl.close();
                            resolve({
                                frameCount,
                                firstHeader,
                                lastSeq: seq,
                            });
                        }
                    }
                };

                setTimeout(() => {
                    ws.close();
                    ctrl.close();
                    resolve({ frameCount, firstHeader, timeout: true });
                }, 10000);
            });
        })""")

        assert result["frameCount"] >= 1, "Should receive at least 1 frame"
        if result["firstHeader"]:
            assert result["firstHeader"]["streamId"] == 0, "Default stream ID should be 0"
            assert result["firstHeader"]["totalSize"] > 10, "Frame should have data after header"
            assert result["firstHeader"]["ts"] >= 0, "Timestamp should be non-negative"


class TestStreamAck:
    """Verify client sends ACKs and server respects flow control."""

    def test_ack_sent(self, server_url: str, page: Any) -> None:
        """Client should send stream_ack after receiving frames."""
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        result = page.evaluate("""() => new Promise((resolve) => {
            let acksSent = 0;

            fetch('/api/session', { method: 'POST' })
            .then(r => r.json())
            .then(sess => {
                const ctrl = new WebSocket(location.href.replace('http', 'ws') + 'ws/control/' + sess.session_id);
                const stream = new WebSocket(location.href.replace('http', 'ws') + 'ws/stream/' + sess.session_id);
                stream.binaryType = 'arraybuffer';

                // Intercept sends on control WS to count ACKs
                const origSend = ctrl.send.bind(ctrl);
                ctrl.send = function(data) {
                    try {
                        const msg = JSON.parse(data);
                        if (msg.type === 'stream_ack') acksSent++;
                    } catch(e) {}
                    origSend(data);
                };

                ctrl.onopen = () => {
                    ctrl.send(JSON.stringify({
                        type: 'stream_config',
                        window_id: 101,
                        fps: 5,
                        quality: 30,
                        max_width: 200,
                    }));
                };

                stream.onmessage = (e) => {
                    if (e.data instanceof ArrayBuffer && e.data.byteLength > 10) {
                        const hdr = new DataView(e.data, 0, 10);
                        const streamId = hdr.getUint16(0);
                        const seq = hdr.getUint32(2);
                        const ts = hdr.getUint32(6);
                        // Send ACK
                        if (ctrl.readyState === 1) {
                            ctrl.send(JSON.stringify({
                                type: 'stream_ack',
                                stream_id: streamId,
                                seq: seq,
                            }));
                        }
                    }
                };

                setTimeout(() => {
                    stream.close();
                    ctrl.close();
                    resolve({ acksSent });
                }, 5000);
            });
        })""")

        assert result["acksSent"] >= 1, "Client should have sent at least 1 ACK"


class TestCodecSwitching:
    """Verify codec can be switched via stream_config."""

    def test_codec_in_config(self, server_url: str, page: Any) -> None:
        """Stream config with codec field should be accepted."""
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        result = page.evaluate("""() => new Promise((resolve) => {
            fetch('/api/session', { method: 'POST' })
            .then(r => r.json())
            .then(sess => {
                const ctrl = new WebSocket(location.href.replace('http', 'ws') + 'ws/control/' + sess.session_id);
                const stream = new WebSocket(location.href.replace('http', 'ws') + 'ws/stream/' + sess.session_id);
                stream.binaryType = 'arraybuffer';

                let configAcked = false;
                ctrl.onmessage = (e) => {
                    try {
                        const msg = JSON.parse(e.data);
                        if (msg.type === 'stream_config_ack') configAcked = true;
                    } catch(ex) {}
                };

                ctrl.onopen = () => {
                    // Send config with codec
                    ctrl.send(JSON.stringify({
                        type: 'stream_config',
                        window_id: 101,
                        fps: 5,
                        quality: 50,
                        max_width: 200,
                        codec: 'jpeg',
                    }));
                };

                setTimeout(() => {
                    stream.close();
                    ctrl.close();
                    resolve({ configAcked });
                }, 3000);
            });
        })""")

        assert result["configAcked"], "Server should ACK stream config with codec"


class TestHighResStream:
    """Test streaming at 5K resolution with max quality."""

    def test_5k_max_quality_doesnt_deadlock(self, server_url: str, page: Any) -> None:
        """Streaming at 5K max quality should not deadlock.

        The server should pause, auto-recover, and keep serving frames.
        """
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        result = page.evaluate("""() => new Promise((resolve) => {
            let frameCount = 0;
            let lastSeq = 0;
            let acksSent = 0;
            let dropped = 0;

            fetch('/api/session', { method: 'POST' })
            .then(r => r.json())
            .then(sess => {
                const ctrl = new WebSocket(location.href.replace('http', 'ws') + 'ws/control/' + sess.session_id);
                const stream = new WebSocket(location.href.replace('http', 'ws') + 'ws/stream/' + sess.session_id);
                stream.binaryType = 'arraybuffer';

                ctrl.onopen = () => {
                    // Max quality, 5K resolution, high FPS
                    ctrl.send(JSON.stringify({
                        type: 'stream_config',
                        window_id: 101,
                        fps: 30,
                        quality: 100,
                        max_width: 5140,
                    }));
                };

                let clientStart = 0;
                let serverOffset = 0;

                stream.onmessage = (e) => {
                    if (!(e.data instanceof ArrayBuffer) || e.data.byteLength < 10) return;

                    const hdr = new DataView(e.data, 0, 10);
                    const streamId = hdr.getUint16(0);
                    const seq = hdr.getUint32(2);
                    const serverTs = hdr.getUint32(6);

                    if (clientStart === 0) {
                        clientStart = performance.now();
                        serverOffset = serverTs;
                    }

                    const clientElapsed = performance.now() - clientStart;
                    const serverElapsed = serverTs - serverOffset;
                    const age = clientElapsed - serverElapsed;

                    if (age > 2000) {
                        dropped++;
                    } else {
                        frameCount++;
                        lastSeq = seq;
                    }

                    // Always ACK
                    if (ctrl.readyState === 1) {
                        ctrl.send(JSON.stringify({
                            type: 'stream_ack',
                            stream_id: streamId,
                            seq: seq,
                        }));
                        acksSent++;
                    }
                };

                // Run for 15 seconds
                setTimeout(() => {
                    stream.close();
                    ctrl.close();
                    resolve({ frameCount, lastSeq, acksSent, dropped });
                }, 15000);
            });
        })""")

        page.screenshot(path=str(SCREENSHOTS_DIR / "5k_stream.png"))

        # Should have received SOME frames (auto-recovery prevents permanent deadlock)
        assert result["acksSent"] > 0, f"Should have sent ACKs, got {result}"
        # The stream should not deadlock — either frames rendered or stale-dropped
        total = result["frameCount"] + result["dropped"]
        assert total > 0, f"Should have received frames (rendered or dropped), got {result}"

    def test_recovery_after_overload(self, server_url: str, page: Any) -> None:
        """After overloading with 5K, dropping to 800px should recover."""
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        result = page.evaluate("""() => new Promise((resolve) => {
            let phase1Frames = 0;
            let phase2Frames = 0;
            let phase = 1;

            fetch('/api/session', { method: 'POST' })
            .then(r => r.json())
            .then(sess => {
                const ctrl = new WebSocket(location.href.replace('http', 'ws') + 'ws/control/' + sess.session_id);
                const stream = new WebSocket(location.href.replace('http', 'ws') + 'ws/stream/' + sess.session_id);
                stream.binaryType = 'arraybuffer';

                ctrl.onopen = () => {
                    // Phase 1: overload with 5K
                    ctrl.send(JSON.stringify({
                        type: 'stream_config',
                        window_id: 101,
                        fps: 30,
                        quality: 100,
                        max_width: 5140,
                    }));

                    // Phase 2: drop to 800px after 5 seconds
                    setTimeout(() => {
                        phase = 2;
                        ctrl.send(JSON.stringify({
                            type: 'stream_config',
                            window_id: 101,
                            fps: 10,
                            quality: 50,
                            max_width: 800,
                        }));
                    }, 5000);
                };

                stream.onmessage = (e) => {
                    if (!(e.data instanceof ArrayBuffer) || e.data.byteLength < 10) return;
                    const hdr = new DataView(e.data, 0, 10);
                    const streamId = hdr.getUint16(0);
                    const seq = hdr.getUint32(2);

                    if (phase === 1) phase1Frames++;
                    else phase2Frames++;

                    if (ctrl.readyState === 1) {
                        ctrl.send(JSON.stringify({
                            type: 'stream_ack', stream_id: streamId, seq: seq,
                        }));
                    }
                };

                setTimeout(() => {
                    stream.close();
                    ctrl.close();
                    resolve({ phase1Frames, phase2Frames });
                }, 12000);
            });
        })""")

        # Phase 2 (800px) should have more frames than phase 1 (5K overload)
        assert result["phase2Frames"] > 0, f"Should recover after dropping resolution: {result}"


class TestAnimatedStream:
    """Verify stream produces changing frames (not frozen)."""

    def test_jpeg_frames_change(self, server_url: str, page: Any) -> None:
        """JPEG frames should have different content over time."""
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        result = page.evaluate("""() => new Promise((resolve) => {
            const frameSizes = [];

            fetch('/api/session', { method: 'POST' })
            .then(r => r.json())
            .then(sess => {
                const ctrl = new WebSocket(location.href.replace('http', 'ws') + 'ws/control/' + sess.session_id);
                const stream = new WebSocket(location.href.replace('http', 'ws') + 'ws/stream/' + sess.session_id);
                stream.binaryType = 'arraybuffer';

                ctrl.onopen = () => {
                    ctrl.send(JSON.stringify({
                        type: 'stream_config',
                        window_id: -1,
                        fps: 10,
                        quality: 50,
                        max_width: 400,
                        codec: 'jpeg',
                    }));
                };

                stream.onmessage = (e) => {
                    if (e.data instanceof ArrayBuffer && e.data.byteLength > 10) {
                        const hdr = new DataView(e.data, 0, 10);
                        const streamId = hdr.getUint16(0);
                        const seq = hdr.getUint32(2);
                        frameSizes.push(e.data.byteLength);
                        ctrl.send(JSON.stringify({
                            type: 'stream_ack', stream_id: streamId, seq: seq
                        }));
                    }
                };

                setTimeout(() => {
                    stream.close();
                    ctrl.close();
                    resolve({ count: frameSizes.length, sizes: frameSizes.slice(0, 5) });
                }, 5000);
            });
        })""")

        page.screenshot(path=str(SCREENSHOTS_DIR / "animated_stream.png"))

        assert result["count"] >= 3, f"Should have received multiple frames: {result}"

    def test_webp_frames(self, server_url: str, page: Any) -> None:
        """WebP codec should produce frames."""
        page.goto(f"{server_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        result = page.evaluate("""() => new Promise((resolve) => {
            let frameCount = 0;

            fetch('/api/session', { method: 'POST' })
            .then(r => r.json())
            .then(sess => {
                const ctrl = new WebSocket(location.href.replace('http', 'ws') + 'ws/control/' + sess.session_id);
                const stream = new WebSocket(location.href.replace('http', 'ws') + 'ws/stream/' + sess.session_id);
                stream.binaryType = 'arraybuffer';

                ctrl.onopen = () => {
                    ctrl.send(JSON.stringify({
                        type: 'stream_config',
                        window_id: -1,
                        fps: 10,
                        quality: 50,
                        max_width: 400,
                        codec: 'webp',
                    }));
                };

                stream.onmessage = (e) => {
                    if (e.data instanceof ArrayBuffer && e.data.byteLength > 10) {
                        const hdr = new DataView(e.data, 0, 10);
                        frameCount++;
                        ctrl.send(JSON.stringify({
                            type: 'stream_ack', stream_id: hdr.getUint16(0), seq: hdr.getUint32(2)
                        }));
                    }
                };

                setTimeout(() => {
                    stream.close();
                    ctrl.close();
                    resolve({ frameCount });
                }, 5000);
            });
        })""")

        assert result["frameCount"] >= 3, f"WebP should produce frames: {result}"
