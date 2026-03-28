"""Tests for hort.peer2peer.punch."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from hort.peer2peer.models import NatType, PeerInfo, PunchResult, StunResult
from hort.peer2peer.proto import Packet, PacketType, make_ping, make_pong
from hort.peer2peer.punch import HolePuncher, _PunchProtocol


class TestPunchProtocol:
    def test_ping_triggers_pong_and_sets_received(self) -> None:
        proto = _PunchProtocol()
        transport = MagicMock()
        proto.connection_made(transport)

        ping_data = make_ping(42)
        proto.datagram_received(ping_data, ("5.6.7.8", 9012))

        assert proto.received.is_set()
        assert proto.remote_addr == ("5.6.7.8", 9012)
        # Should have sent a PONG back
        transport.sendto.assert_called_once()
        pong_data = transport.sendto.call_args[0][0]
        pkt = Packet.decode(pong_data)
        assert pkt.ptype == PacketType.PONG
        assert pkt.seq == 42

    def test_pong_sets_received(self) -> None:
        proto = _PunchProtocol()
        transport = MagicMock()
        proto.connection_made(transport)

        pong_data = make_pong(7)
        proto.datagram_received(pong_data, ("1.2.3.4", 5678))

        assert proto.received.is_set()
        assert proto.remote_addr == ("1.2.3.4", 5678)

    def test_invalid_data_ignored(self) -> None:
        proto = _PunchProtocol()
        proto.connection_made(MagicMock())
        proto.datagram_received(b"garbage", ("1.2.3.4", 5678))
        assert not proto.received.is_set()

    def test_error_received(self) -> None:
        proto = _PunchProtocol()
        proto.error_received(OSError("test"))  # should not raise

    def test_connection_lost(self) -> None:
        proto = _PunchProtocol()
        proto.connection_lost(None)  # should not raise

    def test_ping_without_transport(self) -> None:
        """PING received before transport assigned — no PONG sent, but still sets received."""
        proto = _PunchProtocol()
        # transport is None
        ping_data = make_ping(1)
        proto.datagram_received(ping_data, ("1.2.3.4", 5678))
        assert proto.received.is_set()


class TestHolePuncher:
    @pytest.mark.asyncio
    async def test_punch_success(self) -> None:
        """Simulate a successful hole punch."""
        local = StunResult(
            public_ip="1.2.3.4", public_port=5678,
            local_ip="10.0.0.1", local_port=0,  # 0 = OS picks
        )
        remote = PeerInfo(
            peer_id="remote",
            public_ip="5.6.7.8", public_port=9012,
        )

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            probe_count = 0

            def sendto(data, addr):
                nonlocal probe_count
                probe_count += 1
                # On second probe, simulate receiving a PONG
                if probe_count >= 2:
                    pong = make_pong(1)
                    proto.datagram_received(pong, ("5.6.7.8", 9012))

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        puncher = HolePuncher(local, remote, timeout=5.0)

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            result = await puncher.punch()

        assert result.success is True
        assert result.remote_addr == ("5.6.7.8", 9012)

    @pytest.mark.asyncio
    async def test_punch_timeout(self) -> None:
        """No response → timeout."""
        local = StunResult(
            public_ip="1.2.3.4", public_port=5678,
            local_ip="10.0.0.1", local_port=0,
        )
        remote = PeerInfo(
            peer_id="remote",
            public_ip="5.6.7.8", public_port=9012,
        )

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            transport.sendto = MagicMock()
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        puncher = HolePuncher(local, remote, timeout=0.3)

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            result = await puncher.punch()

        assert result.success is False
        assert "timeout" in result.error

    @pytest.mark.asyncio
    async def test_punch_with_signaling_success(self) -> None:
        """Full flow: signaling exchange + punch."""
        from hort.peer2peer.signal import CallbackSignaling

        sent: list[dict] = []

        async def on_send(data: dict) -> None:
            sent.append(data)

        signal = CallbackSignaling(on_send=on_send)

        stun_result = StunResult(
            public_ip="1.2.3.4", public_port=5678,
            local_ip="10.0.0.1", local_port=0,
        )

        # Deliver remote answer
        async def deliver_remote() -> None:
            await asyncio.sleep(0.01)
            await signal.deliver({
                "peer_id": "remote",
                "public_ip": "5.6.7.8",
                "public_port": 9012,
                "nat_type": "port-restricted",
            })

        asyncio.create_task(deliver_remote())

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()

            def sendto(data, addr):
                pong = make_pong(0)
                proto.datagram_received(pong, ("5.6.7.8", 9012))

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            result = await HolePuncher.punch_with_signaling(
                stun_result, signal, "local-peer", timeout=5.0,
            )

        assert result.success is True
        assert len(sent) == 1  # offer was sent

    @pytest.mark.asyncio
    async def test_punch_with_signaling_timeout(self) -> None:
        """Signaling timeout when peer doesn't respond."""
        from hort.peer2peer.signal import CallbackSignaling

        async def on_send(data: dict) -> None:
            pass

        signal = CallbackSignaling(on_send=on_send)
        stun_result = StunResult(
            public_ip="1.2.3.4", public_port=5678,
            local_ip="10.0.0.1", local_port=0,
        )

        result = await HolePuncher.punch_with_signaling(
            stun_result, signal, "local", timeout=0.05,
        )

        assert result.success is False
        assert "signaling timeout" in result.error
