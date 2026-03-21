"""Self-signed TLS certificate generation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hort.network import get_lan_ip


def _run_openssl(cert_path: Path, key_path: Path, lan_ip: str) -> None:
    """Run openssl to generate a self-signed certificate."""
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "365",
            "-nodes",
            "-subj",
            "/CN=llming-control",
            "-addext",
            f"subjectAltName=IP:{lan_ip},IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )


def ensure_certs(cert_dir: Path, lan_ip: str | None = None) -> tuple[Path, Path]:
    """Ensure self-signed TLS certificates exist.

    Args:
        cert_dir: Directory to store cert.pem and key.pem.
        lan_ip: LAN IP for the SAN extension. Auto-detected if None.

    Returns:
        Tuple of (cert_path, key_path).
    """
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"

    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    cert_dir.mkdir(parents=True, exist_ok=True)

    if lan_ip is None:
        lan_ip = get_lan_ip()

    _run_openssl(cert_path, key_path, lan_ip)

    return cert_path, key_path
