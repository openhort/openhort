"""OpenHort tunnel client built on llming-com remote access."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from llming_com.access.remote import TunnelClient as _LlmingTunnelClient

logger = logging.getLogger(__name__)


class TunnelClient(_LlmingTunnelClient):
    """Connects an OpenHort host to an access hub.

    The transport/proxy protocol lives in llming-com.  This subclass keeps
    OpenHort's historical status-file behavior for the UI.
    """

    def __init__(
        self,
        access_server_url: str,
        connection_key: str,
        local_url: str = "http://localhost:8940",
        *,
        status_file: str | Path = "/tmp/hort-tunnel.active",
    ) -> None:
        super().__init__(
            access_server_url,
            connection_key,
            local_url=local_url,
        )
        self.status_file = Path(status_file)

    async def _read_welcome(self, websocket: Any) -> None:
        await super()._read_welcome(websocket)
        self.status_file.write_text(f"{self.access_server_url}\n{self.host_id}")

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            try:
                self.status_file.unlink(missing_ok=True)
            except OSError:
                pass

    async def stop(self) -> None:
        await super().stop()
        try:
            self.status_file.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> None:  # pragma: no cover
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="openhort tunnel client")
    parser.add_argument("--server", required=True, help="Access server URL (e.g. http://localhost:8400)")
    parser.add_argument("--key", required=True, help="Connection key from the access server")
    parser.add_argument("--local", default="http://localhost:8940", help="Local openhort URL")
    args = parser.parse_args()

    client = TunnelClient(args.server, args.key, args.local)
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
