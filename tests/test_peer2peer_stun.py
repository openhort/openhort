"""Tests for hort.peer2peer.stun."""

from __future__ import annotations

import asyncio
import os
import socket
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hort.peer2peer.models import NatType
from hort.peer2peer.stun import (
    STUN_ATTR_MAPPED_ADDRESS,
    STUN_ATTR_XOR_MAPPED_ADDRESS,
    STUN_BINDING_REQUEST,
    STUN_BINDING_RESPONSE,
    STUN_HEADER_SIZE,
    STUN_MAGIC_COOKIE,
    StunClient,
    _StunProtocol,
    _build_binding_request,
    _parse_binding_response,
)


def _make_stun_response(
    txn_id: bytes,
    ip: str = "1.2.3.4",
    port: int = 5678,
    xor: bool = True,
) -> bytes:
    """Build a synthetic STUN Binding Response."""
    ip_int = struct.unpack("!I", socket.inet_aton(ip))[0]

    if xor:
        xor_port = port ^ (STUN_MAGIC_COOKIE >> 16)
        xor_ip = ip_int ^ STUN_MAGIC_COOKIE
        attr_data = struct.pack("!BBH", 0, 0x01, xor_port) + struct.pack("!I", xor_ip)
        attr_type = STUN_ATTR_XOR_MAPPED_ADDRESS
    else:
        attr_data = struct.pack("!BBH", 0, 0x01, port) + socket.inet_aton(ip)
        attr_type = STUN_ATTR_MAPPED_ADDRESS

    attr = struct.pack("!HH", attr_type, len(attr_data)) + attr_data
    header = struct.pack("!HHI", STUN_BINDING_RESPONSE, len(attr), STUN_MAGIC_COOKIE)
    return header + txn_id + attr


class TestBuildBindingRequest:
    def test_request_size(self) -> None:
        pkt, txn_id = _build_binding_request()
        assert len(pkt) == STUN_HEADER_SIZE
        assert len(txn_id) == 12

    def test_message_type(self) -> None:
        pkt, _ = _build_binding_request()
        msg_type = struct.unpack("!H", pkt[:2])[0]
        assert msg_type == STUN_BINDING_REQUEST

    def test_unique_txn_ids(self) -> None:
        _, txn1 = _build_binding_request()
        _, txn2 = _build_binding_request()
        assert txn1 != txn2


class TestParseBindingResponse:
    def test_xor_mapped_address(self) -> None:
        txn_id = os.urandom(12)
        response = _make_stun_response(txn_id, "93.184.216.34", 12345, xor=True)
        result = _parse_binding_response(response, txn_id)
        assert result is not None
        assert result == ("93.184.216.34", 12345)

    def test_plain_mapped_address(self) -> None:
        txn_id = os.urandom(12)
        response = _make_stun_response(txn_id, "10.0.0.1", 80, xor=False)
        result = _parse_binding_response(response, txn_id)
        assert result is not None
        assert result == ("10.0.0.1", 80)

    def test_wrong_txn_id(self) -> None:
        txn_id = os.urandom(12)
        wrong_txn = os.urandom(12)
        response = _make_stun_response(txn_id)
        result = _parse_binding_response(response, wrong_txn)
        assert result is None

    def test_too_short(self) -> None:
        result = _parse_binding_response(b"\x00" * 10, os.urandom(12))
        assert result is None

    def test_wrong_message_type(self) -> None:
        txn_id = os.urandom(12)
        # Build a non-response
        header = struct.pack("!HHI", 0x0111, 0, STUN_MAGIC_COOKIE)
        data = header + txn_id
        result = _parse_binding_response(data, txn_id)
        assert result is None

    def test_no_matching_attribute(self) -> None:
        txn_id = os.urandom(12)
        # Valid header but unknown attribute
        attr = struct.pack("!HH", 0x9999, 4) + b"\x00\x00\x00\x00"
        header = struct.pack("!HHI", STUN_BINDING_RESPONSE, len(attr), STUN_MAGIC_COOKIE)
        data = header + txn_id + attr
        result = _parse_binding_response(data, txn_id)
        assert result is None


class TestStunProtocol:
    def test_datagram_received_sets_result(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            proto = _StunProtocol.__new__(_StunProtocol)
            proto.transport = None
            proto.response = loop.create_future()
            proto.datagram_received(b"data", ("1.2.3.4", 1234))
            assert proto.response.done()
            assert proto.response.result() == b"data"
        finally:
            loop.close()

    def test_error_received_sets_exception(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            proto = _StunProtocol.__new__(_StunProtocol)
            proto.transport = None
            proto.response = loop.create_future()
            proto.error_received(OSError("test"))
            assert proto.response.done()
            with pytest.raises(OSError):
                proto.response.result()
        finally:
            loop.close()

    def test_connection_lost_sets_exception(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            proto = _StunProtocol.__new__(_StunProtocol)
            proto.transport = None
            proto.response = loop.create_future()
            proto.connection_lost(None)
            assert proto.response.done()
            with pytest.raises(ConnectionError):
                proto.response.result()
        finally:
            loop.close()

    def test_duplicate_datagram_ignored(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            proto = _StunProtocol.__new__(_StunProtocol)
            proto.transport = None
            proto.response = loop.create_future()
            proto.datagram_received(b"first", ("1.2.3.4", 1234))
            proto.datagram_received(b"second", ("1.2.3.4", 1234))
            assert proto.response.result() == b"first"
        finally:
            loop.close()


class TestStunClient:
    @pytest.mark.asyncio
    async def test_discover_success(self) -> None:
        txn_id_holder: list[bytes] = []

        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("192.168.1.10", 54321)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                # Extract txn_id from request
                t_id = data[8:20]
                txn_id_holder.append(t_id)
                resp = _make_stun_response(t_id, "1.2.3.4", 5678)
                proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("stun.test.com", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.discover()

        assert result.public_ip == "1.2.3.4"
        assert result.public_port == 5678
        assert result.local_ip == "192.168.1.10"
        assert result.local_port == 54321

    @pytest.mark.asyncio
    async def test_discover_all_fail(self) -> None:
        async def fail_endpoint(factory, local_addr=None):
            raise OSError("no network")

        client = StunClient(
            stun_servers=[("bad1.test", 1), ("bad2.test", 2)],
            timeout=0.1,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fail_endpoint,
        ):
            with pytest.raises(TimeoutError, match="all STUN servers failed"):
                await client.discover()

    @pytest.mark.asyncio
    async def test_detect_nat_type_symmetric(self) -> None:
        """Two STUN servers returning different ports → symmetric NAT."""
        call_count = 0

        async def fake_endpoint(factory, local_addr=None):
            nonlocal call_count
            call_count += 1
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            mapped_port = 5678 if call_count == 1 else 9999  # different = symmetric

            def sendto(data, addr):
                t_id = data[8:20]
                resp = _make_stun_response(t_id, "1.2.3.4", mapped_port)
                proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478), ("s2.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        assert result.nat_type == NatType.SYMMETRIC

    @pytest.mark.asyncio
    async def test_detect_nat_type_cone(self) -> None:
        """Two STUN servers returning same port → cone NAT."""
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                t_id = data[8:20]
                resp = _make_stun_response(t_id, "1.2.3.4", 5678)
                proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478), ("s2.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        assert result.nat_type == NatType.PORT_RESTRICTED

    @pytest.mark.asyncio
    async def test_detect_nat_type_open(self) -> None:
        """Public IP matches local IP → open/no NAT."""
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("93.184.216.34", 5678)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                t_id = data[8:20]
                resp = _make_stun_response(t_id, "93.184.216.34", 5678)
                proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478), ("s2.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        assert result.nat_type == NatType.OPEN

    @pytest.mark.asyncio
    async def test_detect_nat_type_fallback_single_server(self) -> None:
        """With only one STUN server, falls back to basic discover."""
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                t_id = data[8:20]
                resp = _make_stun_response(t_id, "1.2.3.4", 5678)
                proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        assert result.public_ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_detect_nat_type_first_endpoint_fails(self) -> None:
        """If first create_datagram_endpoint fails, falls back to discover."""
        call_count = 0

        async def fake_endpoint(factory, local_addr=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("first fails")
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                t_id = data[8:20]
                resp = _make_stun_response(t_id, "1.2.3.4", 5678)
                proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478), ("s2.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        assert result.public_ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_detect_nat_type_second_endpoint_fails(self) -> None:
        """If second create_datagram_endpoint fails, returns first result."""
        call_count = 0

        async def fake_endpoint(factory, local_addr=None):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("second fails")
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                t_id = data[8:20]
                resp = _make_stun_response(t_id, "1.2.3.4", 5678)
                proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478), ("s2.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        assert result.public_ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_detect_nat_type_first_query_fails(self) -> None:
        """If first _query fails (bad response), falls back to discover."""
        call_count = 0

        async def fake_endpoint(factory, local_addr=None):
            nonlocal call_count
            call_count += 1
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                t_id = data[8:20]
                if call_count == 1:
                    # First query returns garbage → invalid STUN response
                    proto.datagram_received(b"\x00" * 30, addr)
                else:
                    resp = _make_stun_response(t_id, "1.2.3.4", 5678)
                    proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478), ("s2.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        # Falls back to discover(), which retries
        assert result.public_ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_detect_nat_type_second_query_fails(self) -> None:
        """If second _query fails, returns first result."""
        call_count = 0

        async def fake_endpoint(factory, local_addr=None):
            nonlocal call_count
            call_count += 1
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                t_id = data[8:20]
                if call_count == 2:
                    # Second query returns garbage
                    proto.datagram_received(b"\x00" * 30, addr)
                else:
                    resp = _make_stun_response(t_id, "1.2.3.4", 5678)
                    proto.datagram_received(resp, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478), ("s2.test", 3478)],
            timeout=2.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            result = await client.detect_nat_type()

        assert result.public_ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_query_invalid_response(self) -> None:
        """_query raises ValueError on unparseable STUN response."""
        async def fake_endpoint(factory, local_addr=None):
            proto = factory()
            transport = MagicMock()
            sock = MagicMock()
            sock.getsockname.return_value = ("10.0.0.1", 44444)
            transport.get_extra_info.return_value = sock

            def sendto(data, addr):
                # Send a valid-looking response with wrong txn_id
                proto.datagram_received(b"\x00" * 30, addr)

            transport.sendto = sendto
            transport.close = MagicMock()
            proto.connection_made(transport)
            return transport, proto

        client = StunClient(
            stun_servers=[("s1.test", 3478)],
            timeout=1.0,
        )
        with patch.object(
            asyncio.get_event_loop(), "create_datagram_endpoint",
            side_effect=fake_endpoint,
        ):
            # discover tries all servers, all fail → TimeoutError
            with pytest.raises(TimeoutError):
                await client.discover()
