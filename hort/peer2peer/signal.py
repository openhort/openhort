"""Signaling channel abstraction for exchanging peer endpoints.

The signaling channel is the "rendezvous" path through which two peers
exchange their STUN-discovered public endpoints before hole punching.

This module provides:
- ``SignalingChannel`` — abstract base for any transport (Telegram, WebSocket, etc.)
- ``CallbackSignaling`` — simple implementation using async callbacks (for testing/embedding)
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine

from hort.peer2peer.models import PeerInfo


class SignalingChannel(ABC):
    """Abstract signaling channel for peer endpoint exchange.

    Implementations deliver PeerInfo between two peers via any transport.
    The protocol is intentionally simple: offer → answer.

    Example implementations:
    - Telegram bot messages
    - WebSocket relay
    - Direct function calls (testing)
    """

    @abstractmethod
    async def send_offer(self, peer_info: PeerInfo) -> None:
        """Send our endpoint info to the remote peer."""

    @abstractmethod
    async def wait_answer(self, timeout: float = 30.0) -> PeerInfo:
        """Wait for the remote peer's endpoint info."""

    @abstractmethod
    async def close(self) -> None:
        """Clean up signaling resources."""

    async def exchange(
        self, local_info: PeerInfo, timeout: float = 30.0
    ) -> PeerInfo:
        """Convenience: send offer and wait for answer."""
        await self.send_offer(local_info)
        return await self.wait_answer(timeout)


class CallbackSignaling(SignalingChannel):
    """Signaling channel using async callbacks.

    Useful for embedding hole punching into existing communication
    channels (e.g., Telegram bot, existing WebSocket).

    Args:
        on_send: Called with serialized PeerInfo dict when sending.
        on_receive: Async queue or future that yields the remote PeerInfo dict.
    """

    def __init__(
        self,
        on_send: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        self._on_send = on_send
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def send_offer(self, peer_info: PeerInfo) -> None:
        await self._on_send(peer_info.to_dict())

    async def wait_answer(self, timeout: float = 30.0) -> PeerInfo:
        data = await asyncio.wait_for(self._inbox.get(), timeout=timeout)
        return PeerInfo.from_dict(data)

    async def deliver(self, data: dict[str, Any] | str) -> None:
        """Deliver a received message into the inbox.

        Call this from your transport when a signaling message arrives.
        Accepts either a dict or a JSON string.
        """
        if isinstance(data, str):
            data = json.loads(data)
        await self._inbox.put(data)

    async def close(self) -> None:
        pass
