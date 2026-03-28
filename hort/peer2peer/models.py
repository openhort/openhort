"""Data models for hole punching."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class NatType(enum.Enum):
    """Detected NAT type based on STUN probing."""

    FULL_CONE = "full-cone"
    RESTRICTED = "restricted"
    PORT_RESTRICTED = "port-restricted"
    SYMMETRIC = "symmetric"
    OPEN = "open"  # no NAT (public IP matches local IP)
    UNKNOWN = "unknown"

    @property
    def punchable(self) -> bool:
        """Whether hole punching is likely to succeed."""
        return self in (
            NatType.FULL_CONE,
            NatType.RESTRICTED,
            NatType.PORT_RESTRICTED,
            NatType.OPEN,
        )


@dataclass(frozen=True)
class StunResult:
    """Result of STUN binding discovery."""

    public_ip: str
    public_port: int
    local_ip: str
    local_port: int
    nat_type: NatType = NatType.UNKNOWN

    def to_peer_info(self, peer_id: str) -> PeerInfo:
        """Convert to PeerInfo for signaling exchange."""
        return PeerInfo(
            peer_id=peer_id,
            public_ip=self.public_ip,
            public_port=self.public_port,
            local_ip=self.local_ip,
            local_port=self.local_port,
            nat_type=self.nat_type,
        )


@dataclass(frozen=True)
class PeerInfo:
    """Connection info for a peer, exchanged via signaling."""

    peer_id: str
    public_ip: str
    public_port: int
    local_ip: str = ""
    local_port: int = 0
    nat_type: NatType = NatType.UNKNOWN

    def to_dict(self) -> dict[str, str | int]:
        """Serialize for signaling transport."""
        return {
            "peer_id": self.peer_id,
            "public_ip": self.public_ip,
            "public_port": self.public_port,
            "local_ip": self.local_ip,
            "local_port": self.local_port,
            "nat_type": self.nat_type.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> PeerInfo:
        """Deserialize from signaling transport."""
        return cls(
            peer_id=str(data["peer_id"]),
            public_ip=str(data["public_ip"]),
            public_port=int(data["public_port"]),
            local_ip=str(data.get("local_ip", "")),
            local_port=int(data.get("local_port", 0)),
            nat_type=NatType(str(data.get("nat_type", "unknown"))),
        )


@dataclass(frozen=True)
class PunchResult:
    """Result of a hole punch attempt."""

    success: bool
    local_port: int = 0
    remote_addr: tuple[str, int] = ("", 0)
    rtt_ms: float = 0.0
    error: str = ""
