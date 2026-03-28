"""UDP hole punch coordinator.

Orchestrates the hole punch: both peers simultaneously send UDP packets
to each other's STUN-discovered public endpoint. When a packet gets
through in both directions, the hole is punched.
"""

from __future__ import annotations

import asyncio
import logging
import time

from hort.peer2peer.models import PeerInfo, PunchResult, StunResult
from hort.peer2peer.proto import PacketType, Packet, make_ping, make_pong
from hort.peer2peer.signal import SignalingChannel

logger = logging.getLogger(__name__)

# Punch timing
PROBE_INTERVAL = 0.1  # seconds between probes
MAX_PROBES = 100  # 10 seconds at 0.1s interval
PUNCH_TIMEOUT = 10.0


class _PunchProtocol(asyncio.DatagramProtocol):
    """UDP protocol for hole punch probing."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.received: asyncio.Event = asyncio.Event()
        self.remote_addr: tuple[str, int] = ("", 0)
        self.first_recv_time: float = 0.0

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            pkt = Packet.decode(data)
        except (ValueError, KeyError):
            return

        if pkt.ptype == PacketType.PING:
            # Respond with PONG
            if self.transport:
                self.transport.sendto(make_pong(pkt.seq), addr)
            if not self.received.is_set():
                self.remote_addr = addr
                self.first_recv_time = time.monotonic()
                self.received.set()
        elif pkt.ptype == PacketType.PONG:
            if not self.received.is_set():
                self.remote_addr = addr
                self.first_recv_time = time.monotonic()
                self.received.set()

    def error_received(self, exc: Exception) -> None:
        logger.debug("punch socket error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        pass


class HolePuncher:
    """Coordinates UDP hole punching between two peers.

    Usage::

        puncher = HolePuncher(my_stun_result, remote_peer_info)
        result = await puncher.punch()
        if result.success:
            # result.remote_addr is the working UDP path
            ...
    """

    def __init__(
        self,
        local: StunResult,
        remote: PeerInfo,
        timeout: float = PUNCH_TIMEOUT,
    ) -> None:
        self.local = local
        self.remote = remote
        self.timeout = timeout

    async def punch(self) -> PunchResult:
        """Execute the hole punch.

        Sends PING probes to the remote peer's public endpoint while
        listening for incoming PINGs/PONGs. Returns once bidirectional
        communication is established or timeout is reached.
        """
        loop = asyncio.get_event_loop()
        start = time.monotonic()

        transport, protocol = await loop.create_datagram_endpoint(
            _PunchProtocol,
            local_addr=("0.0.0.0", self.local.local_port),
        )
        protocol: _PunchProtocol  # type: ignore[no-redef]

        target = (self.remote.public_ip, self.remote.public_port)
        logger.info(
            "punching from :%d → %s:%d",
            self.local.local_port,
            target[0],
            target[1],
        )

        try:
            # Send probes while waiting for a response
            for seq in range(MAX_PROBES):
                transport.sendto(make_ping(seq), target)
                try:
                    await asyncio.wait_for(
                        protocol.received.wait(),
                        timeout=PROBE_INTERVAL,
                    )
                    # Got a response
                    elapsed = time.monotonic() - start
                    rtt = (time.monotonic() - protocol.first_recv_time) * 1000
                    logger.info(
                        "hole punched in %.1fs, remote=%s:%d, rtt=%.1fms",
                        elapsed,
                        protocol.remote_addr[0],
                        protocol.remote_addr[1],
                        rtt,
                    )
                    return PunchResult(
                        success=True,
                        local_port=self.local.local_port,
                        remote_addr=protocol.remote_addr,
                        rtt_ms=rtt,
                    )
                except TimeoutError:
                    continue

                if time.monotonic() - start > self.timeout:
                    break

            return PunchResult(
                success=False,
                local_port=self.local.local_port,
                error=f"timeout after {self.timeout}s ({MAX_PROBES} probes)",
            )
        finally:
            transport.close()

    @classmethod
    async def punch_with_signaling(
        cls,
        stun_result: StunResult,
        signal: SignalingChannel,
        peer_id: str,
        timeout: float = PUNCH_TIMEOUT,
    ) -> PunchResult:
        """Full hole punch flow: exchange endpoints via signaling, then punch.

        This is the high-level API that combines signaling + punching.

        Args:
            stun_result: Our STUN-discovered endpoint.
            signal: Signaling channel to exchange endpoints.
            peer_id: Our identifier for the signaling exchange.
            timeout: Max time to wait for the punch.

        Returns:
            PunchResult indicating success or failure.
        """
        local_info = stun_result.to_peer_info(peer_id)

        try:
            remote_info = await signal.exchange(local_info, timeout=timeout)
        except TimeoutError:
            return PunchResult(
                success=False,
                local_port=stun_result.local_port,
                error="signaling timeout — peer did not respond",
            )

        if not remote_info.nat_type.punchable:
            logger.warning(
                "remote peer has %s NAT — punch may fail",
                remote_info.nat_type.value,
            )

        puncher = cls(stun_result, remote_info, timeout=timeout)
        return await puncher.punch()
