"""Compatibility wrapper for the shared llming-com DataChannel proxy."""

from __future__ import annotations

import os

from llming_com.p2p.proxy import DataChannelProxy as _SharedDataChannelProxy
from llming_com.p2p.proxy import WS_ID_LEN


class DataChannelProxy(_SharedDataChannelProxy):
    """OpenHort defaults for the shared DataChannel proxy."""

    def __init__(
        self,
        peer,
        local_base: str = "",
        ws_base: str = "",
    ) -> None:
        port = os.environ.get("HORT_HTTP_PORT", "8940")
        super().__init__(
            peer,
            local_base=local_base or f"http://127.0.0.1:{port}",
            ws_base=ws_base or f"ws://127.0.0.1:{port}",
        )

__all__ = ["DataChannelProxy", "WS_ID_LEN"]
