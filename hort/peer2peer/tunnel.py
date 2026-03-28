"""Reliable UDP tunnel over a punched hole.

Wraps a raw UDP socket into a reliable, ordered byte stream suitable
for proxying TCP traffic (HTTP/WebSocket) over the punched hole.

Features:
- Sequence numbers and ACKs for reliability
- Retransmission with exponential backoff
- Keepalive pings to maintain NAT mapping
- Graceful close with FIN
"""

from __future__ import annotations

import asyncio
import logging
import time

from hort.peer2peer.proto import (
    MAX_PAYLOAD,
    Packet,
    PacketType,
    make_ack,
    make_data,
    make_fin,
    make_ping,
    make_pong,
)

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 15.0  # seconds
RETRANSMIT_TIMEOUT = 0.5  # initial retransmit timeout
MAX_RETRANSMITS = 5
RECV_QUEUE_MAX = 256


class _TunnelProtocol(asyncio.DatagramProtocol):
    """Low-level UDP protocol for the tunnel."""

    def __init__(self, remote_addr: tuple[str, int]) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.remote_addr = remote_addr
        self._recv_queue: asyncio.Queue[Packet] = asyncio.Queue(maxsize=RECV_QUEUE_MAX)
        self._ack_events: dict[int, asyncio.Event] = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            pkt = Packet.decode(data)
        except (ValueError, KeyError):
            return

        if pkt.ptype == PacketType.ACK:
            evt = self._ack_events.get(pkt.seq)
            if evt:
                evt.set()
        elif pkt.ptype == PacketType.PING:
            if self.transport:
                self.transport.sendto(make_pong(pkt.seq), addr)
        elif pkt.ptype in (PacketType.DATA, PacketType.FIN, PacketType.PONG):
            try:
                self._recv_queue.put_nowait(pkt)
            except asyncio.QueueFull:
                logger.warning("tunnel recv queue full, dropping packet seq=%d", pkt.seq)

    def error_received(self, exc: Exception) -> None:
        logger.debug("tunnel socket error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        pass

    def send_raw(self, data: bytes) -> None:
        """Send raw bytes to the remote peer."""
        if self.transport:
            self.transport.sendto(data, self.remote_addr)

    def register_ack(self, seq: int) -> asyncio.Event:
        """Register an event to wait for an ACK."""
        evt = asyncio.Event()
        self._ack_events[seq] = evt
        return evt

    def unregister_ack(self, seq: int) -> None:
        """Remove ACK tracking for a sequence number."""
        self._ack_events.pop(seq, None)


class UdpTunnel:
    """Reliable bidirectional tunnel over a punched UDP hole.

    Usage::

        tunnel = await UdpTunnel.create(local_port, remote_addr)
        await tunnel.send(b"hello from the other side")
        data = await tunnel.recv()
        await tunnel.close()
    """

    def __init__(
        self,
        protocol: _TunnelProtocol,
        transport: asyncio.DatagramTransport,
    ) -> None:
        self._protocol = protocol
        self._transport = transport
        self._send_seq = 0
        self._closed = False
        self._keepalive_task: asyncio.Task[None] | None = None

    @classmethod
    async def create(
        cls,
        local_port: int,
        remote_addr: tuple[str, int],
        keepalive: bool = True,
    ) -> UdpTunnel:
        """Create a tunnel on an already-punched UDP path.

        Args:
            local_port: The local port used during hole punching.
            remote_addr: The remote (ip, port) discovered during punching.
            keepalive: Whether to send periodic keepalive pings.
        """
        loop = asyncio.get_event_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _TunnelProtocol(remote_addr),
            local_addr=("0.0.0.0", local_port),
        )
        tunnel = cls(protocol, transport)  # type: ignore[arg-type]
        if keepalive:
            tunnel._keepalive_task = asyncio.create_task(tunnel._keepalive_loop())
        return tunnel

    async def send(self, data: bytes) -> None:
        """Send data reliably with retransmission.

        Fragments data into MAX_PAYLOAD-sized chunks. Each chunk is
        sent with a sequence number and retransmitted until ACKed.
        """
        if self._closed:
            msg = "tunnel is closed"
            raise ConnectionError(msg)

        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + MAX_PAYLOAD]
            await self._send_reliable(chunk)
            offset += len(chunk)

    async def _send_reliable(self, payload: bytes) -> None:
        """Send a single chunk with retransmission."""
        seq = self._send_seq
        self._send_seq += 1
        packet_data = make_data(seq, payload)
        ack_event = self._protocol.register_ack(seq)

        try:
            timeout = RETRANSMIT_TIMEOUT
            for attempt in range(MAX_RETRANSMITS):
                self._protocol.send_raw(packet_data)
                try:
                    await asyncio.wait_for(ack_event.wait(), timeout=timeout)
                    return
                except TimeoutError:
                    timeout *= 2  # exponential backoff
                    logger.debug("retransmit seq=%d attempt=%d", seq, attempt + 1)

            msg = f"no ACK for seq={seq} after {MAX_RETRANSMITS} retransmits"
            raise ConnectionError(msg)
        finally:
            self._protocol.unregister_ack(seq)

    async def recv(self, timeout: float = 30.0) -> bytes:
        """Receive the next data payload.

        Automatically sends ACKs for received DATA packets.
        Returns the payload bytes.

        Raises:
            ConnectionError: If a FIN is received (tunnel closed by peer).
            TimeoutError: If no data arrives within timeout.
        """
        if self._closed:
            msg = "tunnel is closed"
            raise ConnectionError(msg)

        pkt = await asyncio.wait_for(
            self._protocol._recv_queue.get(), timeout=timeout
        )

        if pkt.ptype == PacketType.FIN:
            self._closed = True
            msg = "tunnel closed by peer"
            raise ConnectionError(msg)

        if pkt.ptype == PacketType.DATA:
            self._protocol.send_raw(make_ack(pkt.seq))

        return pkt.payload

    async def close(self) -> None:
        """Gracefully close the tunnel."""
        if self._closed:
            return
        self._closed = True

        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        # Send FIN (best effort, no retransmit)
        self._protocol.send_raw(make_fin())
        self._transport.close()

    async def _keepalive_loop(self) -> None:
        """Send periodic pings to keep the NAT mapping alive."""
        seq = 0
        while not self._closed:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            if not self._closed:
                self._protocol.send_raw(make_ping(seq))
                seq += 1

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def remote_addr(self) -> tuple[str, int]:
        return self._protocol.remote_addr
