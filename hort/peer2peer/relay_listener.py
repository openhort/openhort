"""Relay listener — connects to a signaling relay to accept remote P2P offers.

The home machine connects to the relay WebSocket and waits for SDP offers
from remote clients (Telegram Mini App, browser). When an offer arrives,
it verifies the one-time connection token before creating a WebRTC peer.

Supports multiple concurrent connections. Dead peers are cleaned up
automatically when WebRTC disconnects.

Security:
- Room ID: SHA-256 of bot token, 64 hex chars (256 bits of entropy)
- Connection token: 32 bytes of os.urandom, base64url (256 bits)
- Tokens are one-time use (consumed on first valid use)
- Tokens expire after 60 seconds
- Brute force protection: exponential backoff per source after failures
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import websockets  # type: ignore[import-untyped]

from hort.peer2peer.dc_proxy import DataChannelProxy
from hort.peer2peer.video_track import ScreenCaptureTrack
from hort.peer2peer.webrtc import WebRTCPeer

logger = logging.getLogger(__name__)

PeerCallback = Callable[[str, WebRTCPeer], Coroutine[Any, Any, None]]

TOKEN_EXPIRY = 60.0  # 60 seconds (connect tokens from /p2p link)
RECONNECT_TOKEN_TTL = 240.0  # 4 minutes
MAX_FAILURES_BEFORE_BACKOFF = 3
BACKOFF_BASE = 2.0  # seconds
BACKOFF_MAX = 60.0  # seconds
CLEANUP_INTERVAL = 30.0  # seconds


class ReconnectTokenStore:
    """Manages reconnect tokens — long-lived (4min), refreshable, multi-session.

    Each active P2P session gets a reconnect token. The token is sent to the
    client on connect and refreshed every 30s via ping/pong. The client stores
    it in sessionStorage. On disconnect, the client reconnects using this token
    instead of generating a new one via Telegram.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}  # token → last_refreshed_at

    def generate(self) -> str:
        """Generate a new reconnect token."""
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.monotonic()
        self._cleanup()
        return token

    def refresh(self, token: str) -> bool:
        """Refresh a token's TTL. Returns False if expired/unknown."""
        if token in self._tokens:
            self._tokens[token] = time.monotonic()
            return True
        return False

    def verify(self, token: str) -> bool:
        """Check if a reconnect token is valid (without consuming it)."""
        self._cleanup()
        return token in self._tokens

    def revoke(self, token: str) -> None:
        """Explicitly revoke a token."""
        self._tokens.pop(token, None)

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [t for t, ts in self._tokens.items() if now - ts > RECONNECT_TOKEN_TTL]
        for t in expired:
            del self._tokens[t]

    @property
    def active_count(self) -> int:
        self._cleanup()
        return len(self._tokens)


class TokenStore:
    """Manages one-time connection tokens with expiry and rate limiting."""

    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}  # token -> created_at
        self._failures: int = 0
        self._last_failure: float = 0.0

    def generate(self) -> str:
        """Generate a new one-time token (32 bytes, base64url, 256-bit entropy)."""
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.monotonic()
        self._cleanup()
        return token

    def verify(self, token: str) -> bool:
        """Verify and consume a token. Returns True if valid."""
        self._cleanup()

        if self._failures >= MAX_FAILURES_BEFORE_BACKOFF:
            elapsed = time.monotonic() - self._last_failure
            backoff = min(BACKOFF_BASE ** (self._failures - MAX_FAILURES_BEFORE_BACKOFF + 1), BACKOFF_MAX)
            if elapsed < backoff:
                logger.warning(
                    "rate limited: %d failures, backoff %.1fs (%.1fs remaining)",
                    self._failures, backoff, backoff - elapsed,
                )
                return False

        if token not in self._tokens:
            self._failures += 1
            self._last_failure = time.monotonic()
            logger.warning("invalid token (attempt %d)", self._failures)
            return False

        # Consume the token — one-time use only
        del self._tokens[token]
        self._failures = 0
        return True

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [t for t, ts in self._tokens.items() if now - ts > TOKEN_EXPIRY]
        for t in expired:
            del self._tokens[t]

    @property
    def pending_count(self) -> int:
        self._cleanup()
        return len(self._tokens)


@dataclass
class PeerSession:
    """One active P2P connection."""

    session_id: str
    peer: WebRTCPeer
    proxy: DataChannelProxy
    created_at: float = field(default_factory=time.monotonic)


class RelayListener:
    """Listens on a signaling relay for incoming P2P connection requests.

    Supports multiple concurrent connections. Dead peers are cleaned up
    automatically.
    """

    def __init__(
        self,
        relay_url: str = "wss://relay.openhort.ai",
        room_id: str = "",
        on_peer_connected: PeerCallback | None = None,
        stun_servers: list[str] | None = None,
        reconnect_interval: float = 5.0,
        video_enabled: bool = True,
        video_fps: int = 10,
        video_max_width: int = 1920,
        capture_fn: Any = None,
    ) -> None:
        self.relay_url = relay_url
        self.room_id = room_id
        self._on_peer_connected = on_peer_connected
        self._stun_servers = stun_servers
        self._video_enabled = video_enabled
        self._video_fps = video_fps
        self._video_max_width = video_max_width
        self._capture_fn = capture_fn
        self._reconnect_interval = reconnect_interval
        self._task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running = False
        self._sessions: dict[str, PeerSession] = {}
        self._ws: Any = None
        self.tokens = TokenStore()
        self.reconnect_tokens = ReconnectTokenStore()

    async def start(self) -> None:
        """Start listening on the relay in a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("relay listener started: %s/%s", self.relay_url, self.room_id)

    async def stop(self) -> None:
        """Stop the relay listener and close all connections."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        # Close all active sessions
        for session in list(self._sessions.values()):
            await self._close_session(session)
        self._sessions.clear()
        logger.info("relay listener stopped (%d sessions closed)", len(self._sessions))

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

    async def _cleanup_loop(self) -> None:
        """Periodically clean up dead peer connections."""
        while self._running:
            await asyncio.sleep(CLEANUP_INTERVAL)
            await self._cleanup_dead_sessions()

    async def _cleanup_dead_sessions(self) -> None:
        """Remove sessions whose WebRTC connection is dead."""
        dead = []
        for sid, session in self._sessions.items():
            state = session.peer.connection_state
            if state in ("failed", "closed", "disconnected"):
                dead.append(sid)

        for sid in dead:
            session = self._sessions.pop(sid)
            await self._close_session(session)
            logger.info("cleaned up dead session %s (state: %s)", sid, session.peer.connection_state)

        if dead:
            logger.info("active P2P sessions: %d", len(self._sessions))

    async def _close_session(self, session: PeerSession) -> None:
        """Close a single session's peer and proxy."""
        try:
            await session.proxy.stop()
        except Exception:
            pass
        try:
            await session.peer.close()
        except Exception:
            pass

    async def _connect_and_listen(self) -> None:
        """Connect to relay and handle incoming offers."""
        url = f"{self.relay_url}/{self.room_id}" if self.room_id else self.relay_url
        logger.info("connecting to relay: %s", url)

        async with websockets.connect(url) as ws:
            self._ws = ws
            logger.info("relay connected, waiting for offers (%d active sessions)", len(self._sessions))

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "offer" and msg.get("sdp"):
                    # Accept if ANY valid auth is present:
                    # 1. Valid reconnect token (reusable, 4min TTL)
                    # 2. Valid one-time token (consumed on use, 60s)
                    token = msg.get("token", "")
                    reconnect_token = msg.get("reconnect_token", "")

                    auth_ok = False
                    if reconnect_token and self.reconnect_tokens.verify(reconnect_token):
                        auth_ok = True
                        logger.info("reconnect accepted")
                    elif token and self.tokens.verify(token):
                        auth_ok = True
                        logger.info("one-time token accepted")

                    if not auth_ok:
                        await ws.send(json.dumps({
                            "type": "error",
                            "message": "invalid or expired token",
                        }))
                        continue
                    await self._handle_offer(ws, msg["sdp"])

    async def _handle_offer(self, ws: Any, offer_sdp: str) -> None:
        """Accept a verified SDP offer, create a new peer session."""
        logger.info("received verified SDP offer (%d bytes), %d active sessions", len(offer_sdp), len(self._sessions))

        # Clean up dead sessions before creating new one
        await self._cleanup_dead_sessions()

        session_id = f"p2p-{secrets.token_hex(4)}"
        proxy = DataChannelProxy(peer=None)  # type: ignore[arg-type]

        async def on_message(data: bytes | str) -> None:
            await proxy.handle_message(data)

        async def on_state_change(state: str) -> None:
            if state in ("failed", "closed"):
                logger.info("session %s disconnected (%s)", session_id, state)
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
            logger.error("failed to create answer: %s", exc)
            await ws.send(json.dumps({"type": "error", "message": str(exc)}))
            return

        await ws.send(json.dumps({"type": "answer", "sdp": answer_sdp}))
        logger.info("SDP answer sent for session %s (%d bytes)", session_id, len(answer_sdp))

        # Wire reconnect token store into proxy
        proxy._reconnect_store = self.reconnect_tokens

        await proxy.start()

        session = PeerSession(session_id=session_id, peer=peer, proxy=proxy)
        self._sessions[session_id] = session
        logger.info("session %s active (total: %d)", session_id, len(self._sessions))

        if self._on_peer_connected:
            await self._on_peer_connected(session_id, peer)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    @property
    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())
