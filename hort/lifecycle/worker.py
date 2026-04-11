"""Worker base — runs inside the managed subprocess.

The worker connects to the main process via the Unix domain socket
(path from HORT_IPC_PATH env var), sends a hello with its protocol
version, and then exchanges messages.

On SIGUSR1, it reconnects to the IPC socket (hot reload scenario —
main process restarted, new socket).

Usage::

    class TelegramWorker(Worker):
        name = "telegram"
        protocol_version = 1

        async def on_connected(self) -> None:
            # Start Telegram polling, forward updates to main
            ...

        async def on_message(self, msg: dict) -> None:
            # Handle messages from main (e.g. send response)
            ...

    if __name__ == "__main__":
        TelegramWorker().run()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Worker(ABC):
    """Base class for the subprocess side of a ManagedProcess."""

    name: str = ""
    protocol_version: int = 1

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._running = True
        self._ipc_path = os.environ.get("HORT_IPC_PATH", "")

    @abstractmethod
    async def on_connected(self) -> None:
        """Called after IPC handshake succeeds. Start your work here."""

    async def on_message(self, msg: dict[str, Any]) -> None:
        """Handle a message from the main process."""

    async def on_disconnected(self) -> None:
        """Called when IPC drops. Enter buffer mode or pause."""

    async def send(self, msg: dict[str, Any]) -> None:
        """Send a message to the main process."""
        if not self._writer:
            return
        data = json.dumps(msg) + "\n"
        self._writer.write(data.encode())
        await self._writer.drain()

    def run(self) -> None:
        """Entry point — called from __main__."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
            stream=sys.stderr,
        )
        if not self._ipc_path:
            logger.error("[%s] HORT_IPC_PATH not set", self.name)
            sys.exit(1)

        asyncio.run(self._main())

    async def _main(self) -> None:
        # Register SIGUSR1 for reconnect
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGUSR1, self._handle_reconnect_signal)
        loop.add_signal_handler(signal.SIGTERM, self._handle_shutdown_signal)

        await self._connect()

        # Stay alive
        while self._running:
            await asyncio.sleep(1)

            # If disconnected, retry
            if not self._connected and self._running:
                await asyncio.sleep(2)
                await self._connect()

    async def _connect(self) -> None:
        """Connect to the main process IPC socket."""
        try:
            reader, writer = await asyncio.open_unix_connection(self._ipc_path)
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            logger.debug("[%s] IPC connect failed: %s", self.name, exc)
            return

        self._reader = reader
        self._writer = writer

        # Send hello
        hello = json.dumps({
            "type": "hello",
            "protocol_version": self.protocol_version,
            "subprocess": self.name,
            "pid": os.getpid(),
        }) + "\n"
        writer.write(hello.encode())
        await writer.drain()

        # Wait for ack
        try:
            ack_line = await asyncio.wait_for(reader.readline(), timeout=5)
            ack = json.loads(ack_line.decode())
            if ack.get("type") != "hello_ack":
                logger.warning("[%s] Unexpected handshake response: %s", self.name, ack)
                writer.close()
                return
        except Exception:
            logger.warning("[%s] Handshake timeout", self.name)
            writer.close()
            return

        self._connected = True
        logger.info("[%s] Connected to main process", self.name)

        await self.on_connected()

        # Read messages
        asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while self._connected and self._reader:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "shutdown":
                    logger.info("[%s] Shutdown requested by main", self.name)
                    self._running = False
                    break
                elif msg.get("type") == "detach":
                    logger.info("[%s] Detached by main (hot reload)", self.name)
                    self._connected = False
                    break
                else:
                    await self.on_message(msg)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._connected = False
            if self._writer:
                self._writer.close()
                self._writer = None
            self._reader = None
            await self.on_disconnected()

    def _handle_reconnect_signal(self) -> None:
        """SIGUSR1 — main process restarted, reconnect IPC."""
        logger.info("[%s] SIGUSR1 received — reconnecting", self.name)
        self._connected = False
        if self._writer:
            self._writer.close()
            self._writer = None

    def _handle_shutdown_signal(self) -> None:
        """SIGTERM — clean shutdown."""
        logger.info("[%s] SIGTERM received — shutting down", self.name)
        self._running = False
        self._connected = False
