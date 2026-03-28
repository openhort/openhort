"""WebRTC peer for browser-to-server P2P connections.

Uses aiortc to create a server-side WebRTC peer that accepts browser
RTCPeerConnection offers. Supports:
- DataChannel for control messages and HTTP/WS proxy
- Video track (VP8) for hardware-decoded screen streaming
- Audio track (Opus) for sound transport (future)

Usage::

    peer = WebRTCPeer(on_message=handle_browser_message)
    peer.add_video_track(screen_track)  # optional — adds VP8 video stream
    answer_sdp = await peer.accept_offer(offer_sdp)
    await peer.send(frame_bytes)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, RTCDataChannel, MediaStreamTrack  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Callback types
MessageHandler = Callable[[bytes | str], Coroutine[Any, Any, None]]
StateHandler = Callable[[str], Coroutine[Any, Any, None]]


class WebRTCPeer:
    """Server-side WebRTC peer for browser P2P connections.

    Manages one RTCPeerConnection with:
    - A DataChannel for bidirectional control/proxy messages
    - Optional video track (VP8) for screen streaming
    - Optional audio track (Opus) for sound (future)
    """

    def __init__(
        self,
        on_message: MessageHandler | None = None,
        on_state_change: StateHandler | None = None,
        stun_servers: list[str] | None = None,
    ) -> None:
        self._on_message = on_message
        self._on_state_change = on_state_change
        ice_servers = [RTCIceServer(urls=s) for s in (stun_servers or ["stun:stun.l.google.com:19302"])]
        config = RTCConfiguration(iceServers=ice_servers)
        self._pc = RTCPeerConnection(configuration=config)
        self._channel: RTCDataChannel | None = None
        self._video_track: MediaStreamTrack | None = None
        self._connected = asyncio.Event()
        self._closed = False

        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Register event handlers on the peer connection."""

        @self._pc.on("datachannel")  # type: ignore[misc]
        def on_datachannel(channel: RTCDataChannel) -> None:
            self._channel = channel
            logger.info("datachannel opened: %s", channel.label)

            @channel.on("message")  # type: ignore[misc]
            async def on_message(message: bytes | str) -> None:
                if self._on_message:
                    await self._on_message(message)

            @channel.on("open")  # type: ignore[misc]
            def on_open() -> None:
                self._connected.set()

            @channel.on("close")  # type: ignore[misc]
            def on_close() -> None:
                self._connected.clear()

        @self._pc.on("connectionstatechange")  # type: ignore[misc]
        async def on_state() -> None:
            state = self._pc.connectionState
            logger.info("connection state: %s", state)
            if self._on_state_change:
                await self._on_state_change(state)
            if state in ("failed", "closed"):
                self._connected.clear()

    def add_video_track(self, track: MediaStreamTrack) -> None:
        """Add a video track to send to the browser.

        Must be called BEFORE accept_offer(). The track will be included
        in the SDP answer and the browser will receive it as a video stream.

        Args:
            track: An aiortc VideoStreamTrack (e.g., ScreenCaptureTrack).
        """
        self._video_track = track
        self._pc.addTrack(track)
        logger.info("video track added: %s", track.kind)

    def add_audio_track(self, track: MediaStreamTrack) -> None:
        """Add an audio track to send to the browser (future).

        Must be called BEFORE accept_offer().
        """
        self._pc.addTrack(track)
        logger.info("audio track added: %s", track.kind)

    async def accept_offer(self, sdp: str, sdp_type: str = "offer") -> str:
        """Accept a browser SDP offer and return the SDP answer.

        If video/audio tracks were added via add_video_track() or
        add_audio_track(), they will be included in the answer SDP.

        Args:
            sdp: The SDP offer string from the browser.
            sdp_type: SDP type (usually "offer").

        Returns:
            The SDP answer string to send back to the browser.
        """
        offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await self._pc.setRemoteDescription(offer)
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)
        return self._pc.localDescription.sdp  # type: ignore[union-attr]

    async def wait_connected(self, timeout: float = 30.0) -> bool:
        """Wait for the DataChannel to open."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def send(self, data: bytes | str) -> None:
        """Send data over the DataChannel."""
        if self._channel and self._channel.readyState == "open":
            self._channel.send(data)

    async def send_json(self, obj: dict[str, Any]) -> None:
        """Send a JSON object over the DataChannel."""
        await self.send(json.dumps(obj))

    async def close(self) -> None:
        """Close the peer connection and stop tracks."""
        if self._closed:
            return
        self._closed = True
        if self._video_track:
            self._video_track.stop()
        await self._pc.close()

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def connection_state(self) -> str:
        return self._pc.connectionState


class WebRTCPeerRegistry:
    """Manages multiple WebRTC peers (one per browser session).

    Each browser session gets its own peer connection. Peers are
    cleaned up when disconnected.
    """

    def __init__(self) -> None:
        self._peers: dict[str, WebRTCPeer] = {}

    async def create_peer(
        self,
        session_id: str,
        offer_sdp: str,
        on_message: MessageHandler | None = None,
        on_state_change: StateHandler | None = None,
        stun_servers: list[str] | None = None,
    ) -> str:
        """Create a new peer for a session, accept the offer, return answer SDP."""
        # Clean up existing peer for this session
        if session_id in self._peers:
            await self._peers[session_id].close()

        async def on_state_wrapper(state: str) -> None:
            if state in ("failed", "closed"):
                self._peers.pop(session_id, None)
            if on_state_change:
                await on_state_change(state)

        peer = WebRTCPeer(
            on_message=on_message,
            on_state_change=on_state_wrapper,
            stun_servers=stun_servers,
        )
        self._peers[session_id] = peer
        answer_sdp = await peer.accept_offer(offer_sdp)
        return answer_sdp

    def get_peer(self, session_id: str) -> WebRTCPeer | None:
        return self._peers.get(session_id)

    async def send_to(self, session_id: str, data: bytes | str) -> bool:
        """Send data to a specific session's peer. Returns True if sent."""
        peer = self._peers.get(session_id)
        if peer and peer.is_connected:
            await peer.send(data)
            return True
        return False

    async def close_all(self) -> None:
        """Close all peer connections."""
        for peer in list(self._peers.values()):
            await peer.close()
        self._peers.clear()

    @property
    def active_sessions(self) -> list[str]:
        return [sid for sid, p in self._peers.items() if p.is_connected]
