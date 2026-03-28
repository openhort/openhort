"""Relay listener — connects to a signaling relay to accept remote P2P offers.

The home machine connects to the relay WebSocket and waits for SDP offers
from remote clients (Telegram Mini App, browser). When an offer arrives,
it creates a WebRTC peer (aiortc), generates an answer, and sends it back
through the relay. The relay then disconnects — all traffic flows direct.

Usage::

    listener = RelayListener(
        relay_url="wss://relay.openhort.ai",
        room_id="my-room",
        on_peer_connected=handle_new_peer,
    )
    await listener.start()
    # ... listener runs in background ...
    await listener.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets  # type: ignore[import-untyped]

from hort.peer2peer.dc_proxy import DataChannelProxy
from hort.peer2peer.webrtc import WebRTCPeer

logger = logging.getLogger(__name__)

PeerCallback = Callable[[str, WebRTCPeer], Coroutine[Any, Any, None]]


class RelayListener:
    """Listens on a signaling relay for incoming P2P connection requests.

    Connects to the relay WebSocket, waits for SDP offers from remote
    clients, creates aiortc peers, and sends answers back through the relay.
    """

    def __init__(
        self,
        relay_url: str = "wss://relay.openhort.ai",
        room_id: str = "",
        on_peer_connected: PeerCallback | None = None,
        on_message: Callable[[bytes | str], Coroutine[Any, Any, None]] | None = None,
        stun_servers: list[str] | None = None,
        reconnect_interval: float = 5.0,
    ) -> None:
        self.relay_url = relay_url
        self.room_id = room_id
        self._on_peer_connected = on_peer_connected
        self._on_message = on_message
        self._stun_servers = stun_servers
        self._reconnect_interval = reconnect_interval
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._current_peer: WebRTCPeer | None = None
        self._current_proxy: DataChannelProxy | None = None
        self._ws: Any = None

    async def start(self) -> None:
        """Start listening on the relay in a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("relay listener started: %s/%s", self.relay_url, self.room_id)

    async def stop(self) -> None:
        """Stop the relay listener."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._current_peer:
            await self._current_peer.close()
        logger.info("relay listener stopped")

    async def _listen_loop(self) -> None:
        """Reconnecting listen loop."""
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("relay connection error: %s", exc)
                if self._running:
                    await asyncio.sleep(self._reconnect_interval)

    async def _connect_and_listen(self) -> None:
        """Connect to relay and handle one session."""
        url = f"{self.relay_url}/{self.room_id}" if self.room_id else self.relay_url
        logger.info("connecting to relay: %s", url)

        async with websockets.connect(url) as ws:
            self._ws = ws
            logger.info("relay connected, waiting for offers")

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                if msg.get("type") == "offer" and msg.get("sdp"):
                    await self._handle_offer(ws, msg["sdp"])

    async def _handle_offer(self, ws: Any, offer_sdp: str) -> None:
        """Accept an SDP offer, create a peer with proxy, send the answer back."""
        logger.info("received SDP offer (%d bytes)", len(offer_sdp))

        # Clean up previous peer and proxy
        if self._current_proxy:
            await self._current_proxy.stop()
        if self._current_peer:
            await self._current_peer.close()

        # Create proxy first so we can wire it as the message handler
        proxy = DataChannelProxy(peer=None)  # type: ignore[arg-type]

        async def on_message(data: bytes | str) -> None:
            await proxy.handle_message(data)

        peer = WebRTCPeer(
            on_message=on_message,
            stun_servers=self._stun_servers,
        )
        proxy._peer = peer  # wire the peer into the proxy
        self._current_peer = peer
        self._current_proxy = proxy

        try:
            answer_sdp = await peer.accept_offer(offer_sdp)
        except Exception as exc:
            logger.error("failed to create answer: %s", exc)
            await ws.send(json.dumps({"type": "error", "message": str(exc)}))
            return

        # Send answer back through relay
        await ws.send(json.dumps({"type": "answer", "sdp": answer_sdp}))
        logger.info("SDP answer sent via relay (%d bytes)", len(answer_sdp))

        # Start the proxy (HTTP client)
        await proxy.start()
        logger.info("DataChannel proxy started")

        # Notify callback
        if self._on_peer_connected:
            session_id = f"relay-{id(peer)}"
            await self._on_peer_connected(session_id, peer)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running

    @property
    def current_peer(self) -> WebRTCPeer | None:
        return self._current_peer
