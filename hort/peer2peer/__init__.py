"""Reusable UDP hole punching library.

Provides NAT traversal via STUN discovery and coordinated UDP hole punching.
Framework-agnostic — no openhort extension dependencies.

Usage::

    from hort.peer2peer import StunClient, HolePuncher, SignalingChannel

    # 1. Discover public endpoint
    stun = StunClient()
    result = await stun.discover()

    # 2. Exchange endpoints via any signaling channel
    channel = MySignalingChannel(...)
    await channel.send_offer(result.to_peer_info("my-id"))
    peer = await channel.wait_answer()

    # 3. Punch through NAT
    puncher = HolePuncher(result, peer)
    tunnel = await puncher.punch()

    # 4. Use the tunnel
    await tunnel.send(b"hello")
    data = await tunnel.recv()
"""

from hort.peer2peer.models import NatType, PeerInfo, PunchResult, StunResult
from hort.peer2peer.punch import HolePuncher
from hort.peer2peer.signal import SignalingChannel
from hort.peer2peer.stun import StunClient
from hort.peer2peer.tunnel import UdpTunnel
from hort.peer2peer.webrtc import WebRTCPeer, WebRTCPeerRegistry

__all__ = [
    "HolePuncher",
    "NatType",
    "PeerInfo",
    "PunchResult",
    "SignalingChannel",
    "StunClient",
    "StunResult",
    "UdpTunnel",
    "WebRTCPeer",
    "WebRTCPeerRegistry",
]
