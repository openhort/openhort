"""Tests for hort.peer2peer.proto."""

import pytest

from hort.peer2peer.proto import (
    HEADER_SIZE,
    MAX_PAYLOAD,
    Packet,
    PacketType,
    make_ack,
    make_data,
    make_fin,
    make_ping,
    make_pong,
)


class TestPacket:
    def test_encode_decode_roundtrip(self) -> None:
        pkt = Packet(PacketType.DATA, seq=42, payload=b"hello")
        raw = pkt.encode()
        decoded = Packet.decode(raw)
        assert decoded.ptype == PacketType.DATA
        assert decoded.seq == 42
        assert decoded.payload == b"hello"

    def test_empty_payload(self) -> None:
        pkt = Packet(PacketType.PING, seq=0)
        raw = pkt.encode()
        decoded = Packet.decode(raw)
        assert decoded.payload == b""
        assert decoded.ptype == PacketType.PING

    def test_decode_too_short(self) -> None:
        with pytest.raises(ValueError, match="packet too short"):
            Packet.decode(b"\x00\x01")

    def test_decode_truncated_payload(self) -> None:
        pkt = Packet(PacketType.DATA, seq=1, payload=b"hello")
        raw = pkt.encode()
        # Truncate the payload
        with pytest.raises(ValueError, match="payload truncated"):
            Packet.decode(raw[:-2])

    def test_header_size(self) -> None:
        assert HEADER_SIZE == 7

    def test_max_payload_constant(self) -> None:
        assert MAX_PAYLOAD == 1200


class TestPacketType:
    def test_values(self) -> None:
        assert PacketType.PING == 0x01
        assert PacketType.PONG == 0x02
        assert PacketType.DATA == 0x03
        assert PacketType.ACK == 0x04
        assert PacketType.FIN == 0x05


class TestHelpers:
    def test_make_ping(self) -> None:
        raw = make_ping(7)
        pkt = Packet.decode(raw)
        assert pkt.ptype == PacketType.PING
        assert pkt.seq == 7

    def test_make_pong(self) -> None:
        raw = make_pong(3)
        pkt = Packet.decode(raw)
        assert pkt.ptype == PacketType.PONG
        assert pkt.seq == 3

    def test_make_data(self) -> None:
        raw = make_data(10, b"payload")
        pkt = Packet.decode(raw)
        assert pkt.ptype == PacketType.DATA
        assert pkt.seq == 10
        assert pkt.payload == b"payload"

    def test_make_ack(self) -> None:
        raw = make_ack(99)
        pkt = Packet.decode(raw)
        assert pkt.ptype == PacketType.ACK
        assert pkt.seq == 99

    def test_make_fin(self) -> None:
        raw = make_fin()
        pkt = Packet.decode(raw)
        assert pkt.ptype == PacketType.FIN
