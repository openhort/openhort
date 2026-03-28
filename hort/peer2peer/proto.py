"""Wire protocol for the UDP tunnel.

Lightweight packet framing over UDP with sequence numbers and ACKs.

Packet layout (7-byte header + payload):
    [type:1][seq:4][length:2][payload:N]

Types:
    PING  (0x01) — keepalive / hole punch probe
    PONG  (0x02) — response to PING
    DATA  (0x03) — application data
    ACK   (0x04) — acknowledges received DATA
    FIN   (0x05) — close tunnel
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass

HEADER_FMT = "!BIH"  # type(1) + seq(4) + length(2)
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 7 bytes
MAX_PAYLOAD = 1200  # safe UDP payload (below typical MTU)


class PacketType(enum.IntEnum):
    """UDP tunnel packet types."""

    PING = 0x01
    PONG = 0x02
    DATA = 0x03
    ACK = 0x04
    FIN = 0x05


@dataclass(frozen=True)
class Packet:
    """A single tunnel packet."""

    ptype: PacketType
    seq: int
    payload: bytes = b""

    def encode(self) -> bytes:
        """Serialize to wire format."""
        header = struct.pack(HEADER_FMT, self.ptype, self.seq, len(self.payload))
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> Packet:
        """Deserialize from wire format."""
        if len(data) < HEADER_SIZE:
            msg = f"packet too short: {len(data)} < {HEADER_SIZE}"
            raise ValueError(msg)
        ptype_raw, seq, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
        payload = data[HEADER_SIZE : HEADER_SIZE + length]
        if len(payload) != length:
            msg = f"payload truncated: {len(payload)} < {length}"
            raise ValueError(msg)
        return cls(ptype=PacketType(ptype_raw), seq=seq, payload=payload)


def make_ping(seq: int = 0) -> bytes:
    """Create a PING probe packet."""
    return Packet(PacketType.PING, seq).encode()


def make_pong(seq: int = 0) -> bytes:
    """Create a PONG response packet."""
    return Packet(PacketType.PONG, seq).encode()


def make_data(seq: int, payload: bytes) -> bytes:
    """Create a DATA packet."""
    return Packet(PacketType.DATA, seq, payload).encode()


def make_ack(seq: int) -> bytes:
    """Create an ACK packet."""
    return Packet(PacketType.ACK, seq).encode()


def make_fin(seq: int = 0) -> bytes:
    """Create a FIN close packet."""
    return Packet(PacketType.FIN, seq).encode()
