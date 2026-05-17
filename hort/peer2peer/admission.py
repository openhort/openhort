"""Compatibility re-export for shared llming-com relay admission client."""

from llming_com.p2p.admission import P2PAdmissionClient, P2PAdmissionError, RoomRegistration

__all__ = ["P2PAdmissionClient", "P2PAdmissionError", "RoomRegistration"]
