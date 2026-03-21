"""Network utilities: LAN IP detection and QR code generation."""

from __future__ import annotations

import base64
import io
import socket

import qrcode  # type: ignore[import-untyped]
from qrcode.image.pil import PilImage  # type: ignore[import-untyped]


def get_lan_ip() -> str:
    """Detect the local LAN IP address.

    Uses the UDP socket trick: connect to a public IP (without sending data)
    and read the local address. Falls back to 127.0.0.1 if no network.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip: str = sock.getsockname()[0]
            return ip
        finally:
            sock.close()
    except OSError:
        return "127.0.0.1"


def generate_qr_data_uri(url: str) -> str:
    """Generate a QR code as a data URI (PNG base64).

    Args:
        url: The URL to encode in the QR code.

    Returns:
        A data URI string like 'data:image/png;base64,...'
    """
    qr_image: PilImage = qrcode.make(url)
    buf = io.BytesIO()
    qr_image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"
