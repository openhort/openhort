"""WebRTC peer for browser-to-server P2P connections.

Uses aiortc to create a server-side WebRTC peer that accepts browser
RTCPeerConnection offers. The DataChannel carries openhort control
messages and JPEG frames.

Usage::

    peer = WebRTCPeer(on_message=handle_browser_message)
    answer_sdp = await peer.accept_offer(offer_sdp)
    # Send answer_sdp back to browser via signaling
    await peer.send(frame_bytes)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, RTCDataChannel  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Callback types
MessageHandler = Callable[[bytes | str], Coroutine[Any, Any, None]]
StateHandler = Callable[[str], Coroutine[Any, Any, None]]


class WebRTCPeer:
    """Server-side WebRTC peer for browser P2P connections.

    Manages one RTCPeerConnection with a DataChannel for bidirectional
    communication with a browser client.
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

    async def accept_offer(self, sdp: str, sdp_type: str = "offer") -> str:
        """Accept a browser SDP offer and return the SDP answer.

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
        """Close the peer connection."""
        if self._closed:
            return
        self._closed = True
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
