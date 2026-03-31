"""Chat backend — routes connector messages to a chat provider (e.g. Claude Code).

This is the generic chat routing layer that any connector (Telegram, Discord,
web chat, etc.) can use to forward non-command messages to a backend.
The backend could be an LLM (Claude Code), a human operator, or any
other service that accepts text and returns text.

Currently implements a Claude Code backend with MCP bridge access.
The MCP bridge runs as an SSE server subprocess on the host, giving
the chat backend access to all MCPMixin extension tools.

Sessions are per-user and non-persistent (in-memory only).
``/new`` resets the session for a fresh conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class ChatProgressEvent:
    """Progress event emitted during chat processing.

    Connectors decide how to render each event type:
    - ``tool_start``: a tool is being invoked (name in ``detail``)
    - ``thinking``: still processing, no specific tool
    - ``typing``: text is being generated (partial text in ``detail``)

    A web chat might show a spinner with tool names.
    A mobile connector (Telegram) might only show a periodic "typing..." indicator
    and skip individual tool events.
    """

    kind: str  # "tool_start", "thinking", "typing"
    detail: str = ""  # tool name, partial text, etc.
    elapsed_seconds: float = 0.0
    tools_used: list[str] = field(default_factory=list)


# Callback receives a ChatProgressEvent — connector decides what to show
ProgressCallback = Callable[[ChatProgressEvent], Coroutine[Any, Any, None]]


DEFAULT_SYSTEM_PROMPT = (
    "You are a remote desktop assistant. You are connected to the user's macOS "
    "desktop through OpenHORT and can see and interact with it using MCP tools. "
    "Your OWN environment (working directory, installed tools) is IRRELEVANT — "
    "do NOT inspect it. Instead, use the openhort MCP tools to observe the user's desktop.\n\n"
    "Available tools (prefixed with openhort__):\n"
    "- list_windows: list all visible application windows\n"
    "- screenshot: capture the desktop or a specific window (returns an image you can analyze)\n"
    "- get_window_info: detailed window metadata (position, size, space)\n"
    "- get_system_metrics: CPU, memory, disk usage\n"
    "- get_disk_usage: disk partitions and usage\n"
    "- get_clipboard_history: recent clipboard entries\n"
    "- list_processes: running processes\n"
    "- click: click at a position on screen\n"
    "- type_text: type text via keyboard\n"
    "- press_key: press special keys\n\n"
    "When the user asks about what's on screen, in a window, or in a terminal, "
    "ALWAYS use the screenshot tool to look at it — you can see the actual screen content. "
    "Describe what you see in plain text. Keep responses concise for mobile chat."
)

# Type alias for progress callback: async fn(text) that sends intermediate updates
ProgressCallback = Callable[[str], Coroutine[Any, Any, None]]


class MCPBridgeProcess:
    """Manages the MCP bridge SSE server subprocess."""

    def __init__(self, port: int = 0) -> None:
        self._port = port
        self._proc: subprocess.Popen[bytes] | None = None
        self._actual_port: int = 0
        self._mcp_config_path: str = ""

    @property
    def url(self) -> str:
        return f"http://localhost:{self._actual_port}/sse"

    @property
    def mcp_config_path(self) -> str:
        return self._mcp_config_path

    def start(self) -> None:
        """Start the MCP bridge SSE server."""
        if self._proc and self._proc.poll() is None:
            return

        self._proc = subprocess.Popen(
            ["python", "-m", "hort.mcp.server", "--sse", "--port", str(self._port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            ))),
        )

        assert self._proc.stderr is not None
        for line in iter(self._proc.stderr.readline, b""):
            text = line.decode("utf-8", errors="replace").strip()
            logger.info("MCP bridge: %s", text)
            if "SSE server on port" in text:
                self._actual_port = int(text.rsplit("port ", 1)[1])
                break
            if self._proc.poll() is not None:
                logger.error("MCP bridge failed to start")
                return

        config = {
            "mcpServers": {
                "openhort": {
                    "type": "sse",
                    "url": self.url,
                },
            },
        }
        fd, path = tempfile.mkstemp(suffix=".json", prefix="hort-mcp-")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f)
        self._mcp_config_path = path
        logger.info("MCP bridge started on port %d, config: %s", self._actual_port, path)

        import threading

        def _drain_stderr() -> None:
            assert self._proc is not None and self._proc.stderr is not None
            for line in iter(self._proc.stderr.readline, b""):
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("MCP bridge: %s", text)

        threading.Thread(target=_drain_stderr, daemon=True).start()

    def stop(self) -> None:
        """Stop the MCP bridge subprocess."""
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._mcp_config_path:
            try:
                os.unlink(self._mcp_config_path)
            except OSError:
                pass
            self._mcp_config_path = ""

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


class ChatSession:
    """Per-user Claude Code conversation session.

    Sends messages to Claude Code CLI and parses the stream-json output.
    Supports progress callbacks for sending intermediate updates
    (e.g. "Using tool: screenshot..." while waiting for a response).
    """

    def __init__(
        self,
        mcp_config_path: str,
        system_prompt: str,
        model: str | None = None,
        progress_interval: float = 8.0,
    ) -> None:
        self._mcp_config = mcp_config_path
        self._system_prompt = system_prompt
        self._model = model
        self._session_id: str | None = None
        self._lock = asyncio.Lock()
        self._progress_interval = progress_interval

    async def send(
        self,
        message: str,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """Send a message and return the response text.

        Args:
            message: User message text.
            on_progress: Optional async callback for progress updates.
                Called periodically with status text while waiting.
        """
        async with self._lock:
            return await self._run(message, on_progress)

    async def _run(
        self,
        message: str,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]
        if self._model:
            cmd.extend(["--model", self._model])
        if self._session_id:
            cmd.extend(["--resume", self._session_id])
        elif self._system_prompt:
            cmd.extend(["--system-prompt", self._system_prompt])
        if self._mcp_config:
            cmd.extend(["--mcp-config", self._mcp_config])
        cmd.extend(["--append-system-prompt",
                     "IMPORTANT: This is a mobile messaging chat (like Telegram). "
                     "NEVER use markdown: no **, no `, no #, no bullet points with -. "
                     "Use plain text only. Keep responses short (1-3 sentences). "
                     "When you receive screenshot data from tools, describe what you see "
                     "in words — never include raw base64 data in your response."])
        cmd.append(message)

        logger.info("Chat backend: starting claude process")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None

        result_text = ""
        tools_used: list[str] = []
        start_time = time.monotonic()
        last_thinking_update = start_time

        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
            except asyncio.TimeoutError:
                # No output for 2s — emit periodic "thinking" event
                now = time.monotonic()
                if on_progress and (now - last_thinking_update) >= self._progress_interval:
                    await on_progress(ChatProgressEvent(
                        kind="thinking",
                        elapsed_seconds=now - start_time,
                        tools_used=list(tools_used),
                    ))
                    last_thinking_update = now
                continue

            if not line:
                break

            try:
                event = json.loads(line.decode("utf-8", errors="replace").strip())
            except (json.JSONDecodeError, ValueError):
                continue

            etype = event.get("type")

            # Session init
            if etype == "system" and event.get("subtype") == "init":
                self._session_id = event.get("session_id")

            # Tool use tracking
            elif etype == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "tool_use":
                        tool_name = block.get("name", "")
                        if tool_name:
                            short = tool_name.split("__")[-1] if "__" in tool_name else tool_name
                            tools_used.append(short)
                            logger.info("Chat backend: tool call → %s", short)
                            if on_progress:
                                await on_progress(ChatProgressEvent(
                                    kind="tool_start",
                                    detail=short,
                                    elapsed_seconds=time.monotonic() - start_time,
                                    tools_used=list(tools_used),
                                ))

            # Final result
            elif etype == "result":
                result_text = event.get("result", "")
                if not self._session_id:
                    self._session_id = event.get("session_id")

        exit_code = await proc.wait()
        if exit_code != 0:
            logger.warning("Claude process exited with code %d", exit_code)
        text = result_text.strip()
        # Strip any base64 data blobs that leak into the response text
        # (happens when Claude includes MCP image tool results in its answer)
        text = re.sub(r'(?:/9j/|iVBOR)[A-Za-z0-9+/=\n]{200,}', '[image data removed]', text)
        if len(text) > 8000:
            text = text[:8000]
        return text or "(no response)"

    def reset(self) -> None:
        """Reset the session — next message starts a new conversation."""
        self._session_id = None


class ChatBackendManager:
    """Manages chat sessions for all users of a connector.

    Any connector can use this to route non-command messages to Claude Code.
    The MCP bridge provides access to all MCPMixin extension tools.
    """

    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        model: str | None = None,
        progress_interval: float = 8.0,
    ) -> None:
        self._system_prompt = system_prompt
        self._model = model
        self._progress_interval = progress_interval
        self._bridge = MCPBridgeProcess(port=0)
        self._sessions: dict[str, ChatSession] = {}

    def start(self) -> None:
        """Start the MCP bridge."""
        self._bridge.start()

    def stop(self) -> None:
        """Stop the MCP bridge and clear sessions."""
        self._bridge.stop()
        self._sessions.clear()

    @property
    def alive(self) -> bool:
        return self._bridge.alive

    def get_session(self, user_id: str) -> ChatSession:
        """Get or create a session for a user."""
        if user_id not in self._sessions:
            self._sessions[user_id] = ChatSession(
                mcp_config_path=self._bridge.mcp_config_path,
                system_prompt=self._system_prompt,
                model=self._model,
                progress_interval=self._progress_interval,
            )
        return self._sessions[user_id]

    def reset_session(self, user_id: str) -> None:
        """Reset a user's session (new conversation)."""
        session = self._sessions.get(user_id)
        if session:
            session.reset()
