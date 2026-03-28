"""Tests for hort.peer2peer.models."""

from hort.peer2peer.models import NatType, PeerInfo, PunchResult, StunResult


class TestNatType:
    def test_punchable_types(self) -> None:
        assert NatType.FULL_CONE.punchable is True
        assert NatType.RESTRICTED.punchable is True
        assert NatType.PORT_RESTRICTED.punchable is True
        assert NatType.OPEN.punchable is True

    def test_not_punchable_types(self) -> None:
        assert NatType.SYMMETRIC.punchable is False
        assert NatType.UNKNOWN.punchable is False

    def test_values(self) -> None:
        assert NatType.FULL_CONE.value == "full-cone"
        assert NatType.SYMMETRIC.value == "symmetric"
        assert NatType.OPEN.value == "open"


class TestStunResult:
    def test_to_peer_info(self) -> None:
        result = StunResult(
            public_ip="1.2.3.4",
            public_port=5678,
            local_ip="192.168.1.10",
            local_port=12345,
            nat_type=NatType.PORT_RESTRICTED,
        )
        peer = result.to_peer_info("test-peer")
        assert peer.peer_id == "test-peer"
        assert peer.public_ip == "1.2.3.4"
        assert peer.public_port == 5678
        assert peer.local_ip == "192.168.1.10"
        assert peer.local_port == 12345
        assert peer.nat_type == NatType.PORT_RESTRICTED

    def test_defaults(self) -> None:
        result = StunResult(
            public_ip="1.2.3.4", public_port=1234,
            local_ip="10.0.0.1", local_port=1234,
        )
        assert result.nat_type == NatType.UNKNOWN


class TestPeerInfo:
    def test_roundtrip(self) -> None:
        peer = PeerInfo(
            peer_id="abc",
            public_ip="5.6.7.8",
            public_port=9012,
            local_ip="10.0.0.5",
            local_port=3456,
            nat_type=NatType.FULL_CONE,
        )
        data = peer.to_dict()
        restored = PeerInfo.from_dict(data)
        assert restored == peer

    def test_from_dict_defaults(self) -> None:
        data = {"peer_id": "x", "public_ip": "1.1.1.1", "public_port": 100}
        peer = PeerInfo.from_dict(data)
        assert peer.local_ip == ""
        assert peer.local_port == 0
        assert peer.nat_type == NatType.UNKNOWN

    def test_to_dict_keys(self) -> None:
        peer = PeerInfo(peer_id="a", public_ip="1.2.3.4", public_port=80)
        d = peer.to_dict()
        assert set(d.keys()) == {
            "peer_id", "public_ip", "public_port",
            "local_ip", "local_port", "nat_type",
        }


class TestPunchResult:
    def test_success(self) -> None:
        r = PunchResult(
            success=True,
            local_port=1234,
            remote_addr=("5.6.7.8", 9012),
            rtt_ms=12.5,
        )
        assert r.success is True
        assert r.error == ""

    def test_failure(self) -> None:
        r = PunchResult(success=False, error="timeout")
        assert r.success is False
        assert r.local_port == 0
        assert r.remote_addr == ("", 0)
