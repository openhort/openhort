"""Tests for certificate generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hort.cert import _run_openssl, ensure_certs


class TestRunOpenssl:
    def test_calls_openssl(self, tmp_path: Path) -> None:
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        with patch("hort.cert.subprocess.run") as mock_run:
            _run_openssl(cert_path, key_path, "192.168.1.42")

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "openssl"
        assert "req" in args
        assert "-x509" in args
        assert str(cert_path) in args
        assert str(key_path) in args
        assert "IP:192.168.1.42,IP:127.0.0.1" in args[-1]

    def test_check_true(self, tmp_path: Path) -> None:
        with patch("hort.cert.subprocess.run") as mock_run:
            _run_openssl(tmp_path / "c.pem", tmp_path / "k.pem", "10.0.0.1")
        assert mock_run.call_args[1]["check"] is True


class TestEnsureCerts:
    def test_creates_new_certs(self, tmp_path: Path) -> None:
        cert_dir = tmp_path / "certs"

        with patch("hort.cert._run_openssl") as mock_ssl:
            cert_path, key_path = ensure_certs(cert_dir, lan_ip="192.168.1.42")

        assert cert_path == cert_dir / "cert.pem"
        assert key_path == cert_dir / "key.pem"
        mock_ssl.assert_called_once_with(cert_path, key_path, "192.168.1.42")
        assert cert_dir.exists()

    def test_reuses_existing(self, tmp_path: Path) -> None:
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        (cert_dir / "cert.pem").write_text("cert")
        (cert_dir / "key.pem").write_text("key")

        with patch("hort.cert._run_openssl") as mock_ssl:
            cert_path, key_path = ensure_certs(cert_dir, lan_ip="192.168.1.42")

        mock_ssl.assert_not_called()
        assert cert_path == cert_dir / "cert.pem"
        assert key_path == cert_dir / "key.pem"

    def test_auto_detects_ip(self, tmp_path: Path) -> None:
        cert_dir = tmp_path / "certs"

        with (
            patch("hort.cert._run_openssl") as mock_ssl,
            patch("hort.cert.get_lan_ip", return_value="10.0.0.5"),
        ):
            ensure_certs(cert_dir)

        mock_ssl.assert_called_once()
        assert mock_ssl.call_args[0][2] == "10.0.0.5"

    def test_creates_directory(self, tmp_path: Path) -> None:
        cert_dir = tmp_path / "deep" / "nested" / "certs"
        assert not cert_dir.exists()

        with patch("hort.cert._run_openssl"):
            ensure_certs(cert_dir, lan_ip="192.168.1.1")

        assert cert_dir.exists()

    def test_only_cert_exists_regenerates(self, tmp_path: Path) -> None:
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        (cert_dir / "cert.pem").write_text("cert")
        # key.pem missing

        with patch("hort.cert._run_openssl") as mock_ssl:
            ensure_certs(cert_dir, lan_ip="192.168.1.1")

        mock_ssl.assert_called_once()
