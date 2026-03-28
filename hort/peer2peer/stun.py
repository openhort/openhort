"""STUN client — discovers public IP:port via RFC 5389 Binding Request.

Minimal implementation: only the Binding Request/Response subset needed
for NAT traversal. No external dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import struct

from hort.peer2peer.models import NatType, StunResult

logger = logging.getLogger(__name__)

# STUN constants (RFC 5389)
STUN_MAGIC_COOKIE = 0x2112A442
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020
STUN_HEADER_SIZE = 20

DEFAULT_STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
]


def _build_binding_request() -> tuple[bytes, bytes]:
    """Build a STUN Binding Request. Returns (packet, transaction_id)."""
    txn_id = os.urandom(12)
    header = struct.pack(
        "!HHI",
        STUN_BINDING_REQUEST,
        0,  # message length (no attributes)
        STUN_MAGIC_COOKIE,
    )
    return header + txn_id, txn_id


def _parse_binding_response(data: bytes, txn_id: bytes) -> tuple[str, int] | None:
    """Parse a STUN Binding Response. Returns (ip, port) or None."""
    if len(data) < STUN_HEADER_SIZE:
        return None

    msg_type, msg_len, cookie = struct.unpack("!HHI", data[:8])
    resp_txn = data[8:20]

    if msg_type != STUN_BINDING_RESPONSE:
        return None
    if resp_txn != txn_id:
        return None

    # Parse attributes
    offset = STUN_HEADER_SIZE
    while offset + 4 <= len(data):
        attr_type, attr_len = struct.unpack("!HH", data[offset : offset + 4])
        attr_data = data[offset + 4 : offset + 4 + attr_len]

        if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            if family == 0x01:  # IPv4
                xor_port = struct.unpack("!H", attr_data[2:4])[0]
                xor_ip = struct.unpack("!I", attr_data[4:8])[0]
                port = xor_port ^ (STUN_MAGIC_COOKIE >> 16)
                ip_int = xor_ip ^ STUN_MAGIC_COOKIE
                ip = socket.inet_ntoa(struct.pack("!I", ip_int))
                return (ip, port)

        if attr_type == STUN_ATTR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            if family == 0x01:  # IPv4
                port = struct.unpack("!H", attr_data[2:4])[0]
                ip = socket.inet_ntoa(attr_data[4:8])
                return (ip, port)

        # Attributes are padded to 4-byte boundaries
        offset += 4 + attr_len + (4 - attr_len % 4) % 4

    return None


class _StunProtocol(asyncio.DatagramProtocol):
    """Async UDP protocol for STUN communication."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.response: asyncio.Future[bytes] = asyncio.get_event_loop().create_future()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not self.response.done():
            self.response.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if not self.response.done():
            self.response.set_exception(exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if not self.response.done():
            self.response.set_exception(ConnectionError("connection lost"))


class StunClient:
    """Discovers the local peer's public IP:port mapping via STUN."""

    def __init__(
        self,
        stun_servers: list[tuple[str, int]] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.stun_servers = stun_servers or DEFAULT_STUN_SERVERS
        self.timeout = timeout

    async def discover(self, local_port: int = 0) -> StunResult:
        """Send STUN Binding Request and return the discovered public endpoint.

        Args:
            local_port: Local UDP port to bind (0 = OS assigns).

        Returns:
            StunResult with public and local addresses.

        Raises:
            TimeoutError: If no STUN server responds.
            OSError: If socket creation fails.
        """
        loop = asyncio.get_event_loop()
        last_error: Exception | None = None

        for server_host, server_port in self.stun_servers:
            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    _StunProtocol,
                    local_addr=("0.0.0.0", local_port),
                )
                try:
                    return await self._query(
                        transport, protocol, server_host, server_port  # type: ignore[arg-type]
                    )
                finally:
                    transport.close()
            except (TimeoutError, OSError, ConnectionError, ValueError) as exc:
                last_error = exc
                logger.debug("STUN server %s:%d failed: %s", server_host, server_port, exc)
                continue

        msg = f"all STUN servers failed, last error: {last_error}"
        raise TimeoutError(msg)

    async def _query(
        self,
        transport: asyncio.DatagramTransport,
        protocol: _StunProtocol,
        server_host: str,
        server_port: int,
    ) -> StunResult:
        """Send binding request and parse response."""
        request, txn_id = _build_binding_request()
        transport.sendto(request, (server_host, server_port))

        data = await asyncio.wait_for(protocol.response, timeout=self.timeout)
        result = _parse_binding_response(data, txn_id)
        if result is None:
            msg = "invalid STUN response"
            raise ValueError(msg)

        public_ip, public_port = result
        sock = transport.get_extra_info("socket")
        local_ip, actual_local_port = sock.getsockname() if sock else ("0.0.0.0", 0)

        nat_type = NatType.OPEN if public_ip == local_ip else NatType.UNKNOWN

        return StunResult(
            public_ip=public_ip,
            public_port=public_port,
            local_ip=local_ip,
            local_port=actual_local_port,
            nat_type=nat_type,
        )

    async def detect_nat_type(self, local_port: int = 0) -> StunResult:
        """Enhanced discovery that probes multiple servers to classify NAT type.

        Sends binding requests to two different STUN servers from the same
        local port. If the mapped port differs, the NAT is symmetric.
        """
        if len(self.stun_servers) < 2:
            return await self.discover(local_port)

        loop = asyncio.get_event_loop()
        try:
            transport, protocol1 = await loop.create_datagram_endpoint(
                _StunProtocol,
                local_addr=("0.0.0.0", local_port),
            )
        except OSError:
            return await self.discover(local_port)
        try:
            # Query first server
            result1 = await self._query(
                transport, protocol1, *self.stun_servers[0]  # type: ignore[arg-type]
            )
        except (TimeoutError, OSError, ValueError):
            transport.close()
            return await self.discover(local_port)

        # Reuse the same local port for second query
        actual_port = result1.local_port
        transport.close()

        # Second query from same local port to different server
        try:
            transport2, protocol2 = await loop.create_datagram_endpoint(
                _StunProtocol,
                local_addr=("0.0.0.0", actual_port),
            )
        except OSError:
            return result1
        try:
            result2 = await self._query(
                transport2, protocol2, *self.stun_servers[1]  # type: ignore[arg-type]
            )
        except (TimeoutError, OSError, ValueError):
            transport2.close()
            return result1
        finally:
            transport2.close()

        # Compare mapped ports
        if result1.public_ip == result1.local_ip:
            nat_type = NatType.OPEN
        elif result1.public_port != result2.public_port:
            nat_type = NatType.SYMMETRIC
        else:
            # Same mapped port to different servers = cone NAT
            # (can't distinguish full/restricted/port-restricted without
            # a STUN server that supports CHANGE-REQUEST, which most don't)
            nat_type = NatType.PORT_RESTRICTED  # conservative assumption

        return StunResult(
            public_ip=result1.public_ip,
            public_port=result1.public_port,
            local_ip=result1.local_ip,
            local_port=result1.local_port,
            nat_type=nat_type,
        )
