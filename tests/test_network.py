"""Tests for network utilities."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from PIL import Image
import io

from hort.network import generate_qr_data_uri, get_lan_ip


class TestGetLanIp:
    def test_returns_ip(self) -> None:
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("192.168.1.42", 12345)
        with patch("hort.network.socket.socket", return_value=mock_socket):
            ip = get_lan_ip()
        assert ip == "192.168.1.42"
        mock_socket.connect.assert_called_once_with(("8.8.8.8", 80))
        mock_socket.close.assert_called_once()

    def test_fallback_on_error(self) -> None:
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = OSError("No network")
        with patch("hort.network.socket.socket", return_value=mock_socket):
            ip = get_lan_ip()
        assert ip == "127.0.0.1"

    def test_socket_closed_on_error(self) -> None:
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = OSError("No network")
        with patch("hort.network.socket.socket", return_value=mock_socket):
            get_lan_ip()
        mock_socket.close.assert_called_once()


class TestGenerateQrDataUri:
    def test_returns_data_uri(self) -> None:
        uri = generate_qr_data_uri("https://192.168.1.42:8950")
        assert uri.startswith("data:image/png;base64,")

    def test_valid_base64(self) -> None:
        uri = generate_qr_data_uri("https://example.com")
        b64_part = uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        assert len(decoded) > 0

    def test_valid_png(self) -> None:
        uri = generate_qr_data_uri("https://example.com:8950")
        b64_part = uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        img = Image.open(io.BytesIO(decoded))
        assert img.format == "PNG"
        assert img.width > 0
        assert img.height > 0

    def test_different_urls_different_qr(self) -> None:
        uri1 = generate_qr_data_uri("https://10.0.0.1:8950")
        uri2 = generate_qr_data_uri("https://192.168.1.1:8950")
        assert uri1 != uri2
