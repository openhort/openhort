"""Tests for hort.peer2peer.tunnel."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from hort.peer2peer.proto import Packet, PacketType, make_ack, make_data, make_fin, make_ping
from hort.peer2peer.tunnel import UdpTunnel, _TunnelProtocol


class TestTunnelProtocol:
    def test_ack_sets_event(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        transport = MagicMock()
        proto.connection_made(transport)

        loop = asyncio.new_event_loop()
        try:
            evt = loop.create_future()
            ack_evt = asyncio.Event()
            proto._ack_events[42] = ack_evt
            ack_data = make_ack(42)
            proto.datagram_received(ack_data, ("1.2.3.4", 5678))
            assert ack_evt.is_set()
        finally:
            loop.close()

    def test_ping_sends_pong(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        transport = MagicMock()
        proto.connection_made(transport)

        ping_data = make_ping(3)
        proto.datagram_received(ping_data, ("1.2.3.4", 5678))
        transport.sendto.assert_called_once()
        pong = Packet.decode(transport.sendto.call_args[0][0])
        assert pong.ptype == PacketType.PONG

    def test_data_queued(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.connection_made(MagicMock())

        data_pkt = make_data(1, b"hello")
        proto.datagram_received(data_pkt, ("1.2.3.4", 5678))
        assert not proto._recv_queue.empty()

    def test_fin_queued(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.connection_made(MagicMock())

        fin_data = make_fin(0)
        proto.datagram_received(fin_data, ("1.2.3.4", 5678))
        assert not proto._recv_queue.empty()

    def test_invalid_data_ignored(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.connection_made(MagicMock())
        proto.datagram_received(b"bad", ("1.2.3.4", 5678))
        assert proto._recv_queue.empty()

    def test_send_raw(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        transport = MagicMock()
        proto.connection_made(transport)
        proto.send_raw(b"raw-data")
        transport.sendto.assert_called_once_with(b"raw-data", ("1.2.3.4", 5678))

    def test_register_unregister_ack(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        evt = proto.register_ack(10)
        assert 10 in proto._ack_events
        proto.unregister_ack(10)
        assert 10 not in proto._ack_events

    def test_unregister_nonexistent_ack(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.unregister_ack(999)  # should not raise

    def test_error_received(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.error_received(OSError("test"))  # should not raise

    def test_connection_lost(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.connection_lost(None)  # should not raise

    def test_send_raw_no_transport(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.send_raw(b"data")  # should not raise when transport is None

    def test_queue_full_drops(self) -> None:
        proto = _TunnelProtocol(("1.2.3.4", 5678))
        proto.connection_made(MagicMock())
        # Fill the queue
        for i in range(256):
            data_pkt = make_data(i, b"x")
            proto.datagram_received(data_pkt, ("1.2.3.4", 5678))
        # Next one should be dropped (not raise)
        data_pkt = make_data(999, b"overflow")
        proto.datagram_received(data_pkt, ("1.2.3.4", 5678))
        assert proto._recv_queue.qsize() == 256


class TestUdpTunnel:
    @pytest.mark.asyncio
    async def test_create_and_close(self) -> None:
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(12345, ("5.6.7.8", 9012), keepalive=False)

        assert not tunnel.is_closed
        assert tunnel.remote_addr == ("5.6.7.8", 9012)
        await tunnel.close()
        assert tunnel.is_closed

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        await tunnel.close()
        await tunnel.close()  # should not raise

    @pytest.mark.asyncio
    async def test_send_when_closed(self) -> None:
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        await tunnel.close()
        with pytest.raises(ConnectionError, match="tunnel is closed"):
            await tunnel.send(b"data")

    @pytest.mark.asyncio
    async def test_recv_when_closed(self) -> None:
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        await tunnel.close()
        with pytest.raises(ConnectionError, match="tunnel is closed"):
            await tunnel.recv()

    @pytest.mark.asyncio
    async def test_recv_data_sends_ack(self) -> None:
        transport_ref = MagicMock()

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport_ref.close = MagicMock()
            proto.connection_made(transport_ref)
            return transport_ref, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        # Inject a DATA packet into the protocol's queue
        data_pkt = make_data(7, b"payload")
        tunnel._protocol.datagram_received(data_pkt, ("5.6.7.8", 9012))

        result = await tunnel.recv(timeout=1.0)
        assert result == b"payload"

        # Verify ACK was sent
        send_calls = [c for c in transport_ref.sendto.call_args_list]
        ack_sent = False
        for call in send_calls:
            raw = call[0][0]
            try:
                pkt = Packet.decode(raw)
                if pkt.ptype == PacketType.ACK and pkt.seq == 7:
                    ack_sent = True
            except (ValueError, KeyError):
                pass
        assert ack_sent

    @pytest.mark.asyncio
    async def test_recv_fin_closes(self) -> None:
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        fin_data = make_fin(0)
        tunnel._protocol.datagram_received(fin_data, ("5.6.7.8", 9012))

        with pytest.raises(ConnectionError, match="tunnel closed by peer"):
            await tunnel.recv(timeout=1.0)
        assert tunnel.is_closed

    @pytest.mark.asyncio
    async def test_recv_timeout(self) -> None:
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        with pytest.raises(TimeoutError):
            await tunnel.recv(timeout=0.05)

        await tunnel.close()

    @pytest.mark.asyncio
    async def test_send_reliable_with_ack(self) -> None:
        """Send data and simulate ACK response."""
        transport_ref = MagicMock()

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport_ref.close = MagicMock()
            proto.connection_made(transport_ref)
            return transport_ref, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        # Simulate ACK arriving shortly after send
        async def ack_responder() -> None:
            await asyncio.sleep(0.01)
            ack_data = make_ack(0)
            tunnel._protocol.datagram_received(ack_data, ("5.6.7.8", 9012))

        asyncio.create_task(ack_responder())
        await tunnel.send(b"hello")  # should succeed

        await tunnel.close()

    @pytest.mark.asyncio
    async def test_send_reliable_no_ack_raises(self) -> None:
        """Send data without ACK → ConnectionError after retransmits."""
        transport_ref = MagicMock()

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport_ref.close = MagicMock()
            proto.connection_made(transport_ref)
            return transport_ref, proto

        loop = asyncio.get_event_loop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
            tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=False)

        # Patch retransmit timeout to be very short
        import hort.peer2peer.tunnel as tmod
        orig = tmod.RETRANSMIT_TIMEOUT
        tmod.RETRANSMIT_TIMEOUT = 0.01
        try:
            with pytest.raises(ConnectionError, match="no ACK"):
                await tunnel.send(b"data")
        finally:
            tmod.RETRANSMIT_TIMEOUT = orig
            await tunnel.close()

    @pytest.mark.asyncio
    async def test_keepalive(self) -> None:
        """Keepalive task sends pings."""
        transport_ref = MagicMock()

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport_ref.close = MagicMock()
            proto.connection_made(transport_ref)
            return transport_ref, proto

        loop = asyncio.get_event_loop()

        import hort.peer2peer.tunnel as tmod
        orig_interval = tmod.KEEPALIVE_INTERVAL
        tmod.KEEPALIVE_INTERVAL = 0.02

        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(loop, "create_datagram_endpoint", fake_endpoint)
                tunnel = await UdpTunnel.create(0, ("5.6.7.8", 9012), keepalive=True)

            await asyncio.sleep(0.05)
            await tunnel.close()

            # Should have sent at least one keepalive ping
            ping_sent = False
            for call in transport_ref.sendto.call_args_list:
                raw = call[0][0]
                try:
                    pkt = Packet.decode(raw)
                    if pkt.ptype == PacketType.PING:
                        ping_sent = True
                except (ValueError, KeyError):
                    pass
            assert ping_sent
        finally:
            tmod.KEEPALIVE_INTERVAL = orig_interval
