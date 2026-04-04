"""Relay poller — polls the relay HTTP mailbox for incoming connection requests.

Replaces the persistent WebSocket approach of relay_listener.py. The host
only connects to the relay WebSocket briefly during actual SDP exchange
(~3-5 seconds), then disconnects.

Flow:
1. Poll GET /{room}/pending every poll_interval seconds
2. Validate device_token_hash against DeviceTokenStore (MongoDB)
3. Connect to relay WebSocket (temporary)
4. Generate one-time P2P token, build viewer URL
5. POST URL to /{room}/respond
6. Wait for SDP offer on WebSocket, exchange, establish P2P
7. Disconnect WebSocket after SDP exchange or timeout
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import httpx
from hort.peer2peer.dc_proxy import DataChannelProxy
from hort.peer2peer.device_tokens import DeviceTokenStore
from hort.peer2peer.relay_listener import (
    PeerSession,
    ReconnectTokenStore,
    TokenStore,
)
from hort.peer2peer.webrtc import WebRTCPeer

logger = logging.getLogger(__name__)

PeerCallback = Callable[[str, WebRTCPeer], Coroutine[Any, Any, None]]

SDP_EXCHANGE_TIMEOUT = 60.0  # seconds to wait for SDP offer after connecting WS
CLEANUP_INTERVAL = 15.0  # seconds between dead session cleanup
PAIRING_POLL_INTERVAL = 3.0  # fast polling during pairing (60s window)
PAIRING_TIMEOUT = 60.0  # how long to fast-poll after generating a pairing token


class RelayPoller:
    """Polls the relay HTTP mailbox for connection requests from paired devices.

    Unlike RelayListener (persistent WebSocket), this class only connects to
    the relay WebSocket temporarily for SDP exchange. Between connections,
    it uses lightweight HTTP polling.
    """

    def __init__(
        self,
        relay_url: str = "wss://relay.openhort.ai",
        relay_http_url: str = "https://relay.openhort.ai",
        room_id: str = "",
        device_store: DeviceTokenStore | None = None,
        on_peer_connected: PeerCallback | None = None,
        stun_servers: list[str] | None = None,
        poll_interval: float = 5.0,
        viewer_base: str = "https://openhort.ai/p2p/viewer.html",
    ) -> None:
        self.relay_url = relay_url
        self.relay_http_url = relay_http_url
        self.room_id = room_id
        self._device_store = device_store
        self._on_peer_connected = on_peer_connected
        self._stun_servers = stun_servers
        self._poll_interval = poll_interval
        self._viewer_base = viewer_base
        self._task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running = False
        self._sessions: dict[str, PeerSession] = {}
        self._http: httpx.AsyncClient | None = None
        # One-time tokens for SDP auth (same as relay_listener)
        self.tokens = TokenStore()
        self.reconnect_tokens = ReconnectTokenStore()
        # Temporary fast-poll state (during pairing)
        self._pairing_until: float = 0.0

    async def start(self) -> None:
        """Start the polling loop."""
        if self._running:
            return
        self._running = True
        self._http = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._poll_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("relay poller started: %s/%s (poll every %.0fs)",
                     self.relay_http_url, self.room_id, self._poll_interval)

    async def stop(self) -> None:
        """Stop polling and close all sessions."""
        self._running = False
        for task in [self._task, self._cleanup_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        for session in list(self._sessions.values()):
            await self._close_session(session)
        self._sessions.clear()
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("relay poller stopped")

    def start_pairing_poll(self) -> None:
        """Temporarily switch to fast polling (3s) for pairing confirmation."""
        self._pairing_until = time.monotonic() + PAIRING_TIMEOUT
        logger.info("pairing mode: fast polling for %.0fs", PAIRING_TIMEOUT)

    # --- Polling loop ---

    async def _poll_loop(self) -> None:
        """Main polling loop — GET /{room}/pending periodically."""
        while self._running:
            try:
                interval = self._current_interval()
                await asyncio.sleep(interval)
                if not self._running:
                    break
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("poll error: %s", exc)

    def _current_interval(self) -> float:
        """Return current poll interval (fast during pairing, normal otherwise)."""
        if time.monotonic() < self._pairing_until:
            return PAIRING_POLL_INTERVAL
        return self._poll_interval

    async def _poll_once(self) -> None:
        """Single poll iteration: check for pending requests, handle them."""
        if not self._http:
            return
        url = f"{self.relay_http_url}/{self.room_id}/pending"
        try:
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return
            data = resp.json()
        except Exception as exc:
            logger.debug("poll request failed: %s", exc)
            return

        requests = data.get("requests", [])
        if not requests:
            return

        # Update poll interval from server config
        config = data.get("config", {})
        server_interval = config.get("poll_interval_ms")
        if server_interval and isinstance(server_interval, (int, float)):
            self._poll_interval = server_interval / 1000.0

        for req in requests:
            device_hash = req.get("device_token_hash", "")
            if not device_hash:
                continue
            # Validate against MongoDB store
            if self._device_store and not self._device_store.verify_hash(device_hash):
                logger.warning("rejected unknown device hash: %s...", device_hash[:12])
                continue
            # Mark device as seen
            if self._device_store:
                self._device_store.mark_seen(device_hash)
            # Handle the connection request
            asyncio.create_task(self._handle_request(device_hash))

    # --- Connection handling ---

    async def _handle_request(self, device_token_hash: str) -> None:
        """Handle a validated connection request from a paired device."""
        logger.info("handling connection request from device %s...", device_token_hash[:12])

        if not self._http:
            return

        # 1. Generate one-time P2P auth token
        p2p_token = self.tokens.generate()

        # 2. Build P2P viewer URL
        viewer_url = (
            f"{self._viewer_base}?signal=ws"
            f"&room={self.room_id}"
            f"&token={p2p_token}"
            f"&relay={self.relay_url}"
        )

        # 3. POST response URL to relay mailbox
        respond_url = f"{self.relay_http_url}/{self.room_id}/respond"
        await self._http.post(respond_url, json={
            "device_token_hash": device_token_hash,
            "url": viewer_url,
        })
        logger.info("posted P2P URL for device %s...", device_token_hash[:12])

        # 4. Poll for SDP offer via HTTP and respond via HTTP
        await self.listen_for_sdp_once(timeout=60.0)

    # Old WebSocket-based _wait_for_sdp and _create_session removed.
    # SDP exchange now goes through HTTP: listen_for_sdp_once + _create_session_http

    # --- On-demand SDP listener (for generated links) ---

    async def listen_for_sdp_once(self, timeout: float = 60.0) -> None:
        """Poll relay HTTP for SDP offers and respond via HTTP.

        Used when a P2P link is generated via the UI or API. The viewer
        connects to the relay via WebSocket and posts its SDP offer. The
        relay stores it. We poll for it via HTTP, then post the answer back.
        """
        if not self._http:
            return
        poll_url = f"{self.relay_http_url}/{self.room_id}/sdp-inbox"
        send_url = f"{self.relay_http_url}/{self.room_id}/sdp-send"
        logger.info("polling for SDP offers via HTTP (timeout %.0fs)", timeout)

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await self._http.get(poll_url)
                if resp.status_code == 200:
                    data = resp.json()
                    messages = data.get("messages", [])
                    for msg in messages:
                        if msg.get("type") == "offer" and msg.get("sdp"):
                            # Verify auth
                            token = msg.get("token", "")
                            reconnect_token = msg.get("reconnect_token", "")
                            auth_ok = False
                            if reconnect_token and self.reconnect_tokens.verify(reconnect_token):
                                auth_ok = True
                            elif token and self.tokens.verify(token):
                                auth_ok = True
                            if not auth_ok:
                                await self._http.post(send_url, json={
                                    "type": "error", "message": "invalid or expired token",
                                })
                                continue
                            # Create peer and generate answer
                            answer_sdp = await self._create_session_http(msg["sdp"])
                            if answer_sdp:
                                await self._http.post(send_url, json={
                                    "type": "answer", "sdp": answer_sdp,
                                })
                                logger.info("SDP answer posted via HTTP")
                            return
            except Exception as exc:
                logger.debug("SDP poll error: %s", exc)
            await asyncio.sleep(0.25)  # Poll every 250ms for SDP (time-critical)

        logger.info("on-demand SDP listener timed out (no offer)")

    async def _create_session_http(self, offer_sdp: str) -> str | None:
        """Create a WebRTC peer session and return the SDP answer (no WebSocket needed)."""
        await self._cleanup_dead_sessions()

        session_id = f"p2p-{secrets.token_hex(4)}"
        proxy = DataChannelProxy(peer=None)  # type: ignore[arg-type]

        async def on_message(data: bytes | str) -> None:
            await proxy.handle_message(data)

        async def on_state_change(state: str) -> None:
            logger.info("session %s state: %s", session_id, state)
            if state in ("failed", "closed", "disconnected"):
                logger.info("session %s ended (%s)", session_id, state)
                session = self._sessions.pop(session_id, None)
                if session:
                    await self._close_session(session)

        peer = WebRTCPeer(
            on_message=on_message,
            on_state_change=on_state_change,
            stun_servers=self._stun_servers,
        )
        proxy._peer = peer

        try:
            answer_sdp = await peer.accept_offer(offer_sdp)
        except Exception as exc:
            logger.error("failed to create SDP answer: %s", exc)
            return None

        logger.info("SDP answer created for session %s (%d bytes) — sending before proxy start",
                     session_id, len(answer_sdp))

        # Return answer FIRST so it gets posted to the viewer immediately.
        # Start proxy and register session in background after the answer is sent.
        async def _finish_session() -> None:
            proxy._reconnect_store = self.reconnect_tokens
            await proxy.start()
            session = PeerSession(session_id=session_id, peer=peer, proxy=proxy)
            self._sessions[session_id] = session
            logger.info("session %s active (total: %d)", session_id, len(self._sessions))
            if self._on_peer_connected:
                await self._on_peer_connected(session_id, peer)

        asyncio.create_task(_finish_session())
        return answer_sdp

    # --- Session management ---

    async def _cleanup_loop(self) -> None:
        """Periodically clean up dead peer connections."""
        while self._running:
            await asyncio.sleep(CLEANUP_INTERVAL)
            await self._cleanup_dead_sessions()

    async def _cleanup_dead_sessions(self) -> None:
        dead = []
        for sid, session in self._sessions.items():
            state = session.peer.connection_state
            age = time.monotonic() - session.created_at
            if state in ("failed", "closed", "disconnected"):
                dead.append(sid)
            elif age > 30 and state != "connected":
                # Kill sessions stuck in non-connected state for >30s (ping timeout)
                logger.info("force-killing stale session %s (state=%s, age=%.0fs)", sid, state, age)
                dead.append(sid)
        for sid in dead:
            session = self._sessions.pop(sid)
            await self._close_session(session)
            logger.info("cleaned up dead session %s", sid)

    async def _close_session(self, session: PeerSession) -> None:
        try:
            await session.proxy.stop()
        except Exception:
            pass
        try:
            await session.peer.close()
        except Exception:
            pass

    # --- Properties ---

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    @property
    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())
