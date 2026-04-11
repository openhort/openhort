"""Managed subprocess lifecycle for llmings.

Llmings with background tasks (Telegram polling, camera discovery,
MCP bridge) run as managed subprocesses that survive hot reloads.

Usage::

    from hort.lifecycle import ManagedProcess

    class TelegramPoller(ManagedProcess):
        name = "telegram"
        protocol_version = 1

        def build_command(self) -> list[str]:
            return ["python", "-m", "hort.lifecycle.workers.telegram"]

        async def on_message(self, msg: dict) -> None:
            # Handle messages from the subprocess
            ...

    poller = TelegramPoller()
    await poller.start()        # spawns subprocess, connects IPC
    await poller.send(...)      # send to subprocess
    await poller.stop()         # SIGTERM + cleanup
"""

from hort.lifecycle.manager import ManagedProcess, ProcessManager
from hort.lifecycle.llming_process import GroupProcess, LlmingProcess, LlmingProxy

__all__ = ["ManagedProcess", "ProcessManager", "GroupProcess", "LlmingProcess", "LlmingProxy"]
