"""Chat backend — routes connector messages to a chat provider (e.g. Claude Code).

This is the generic chat routing layer that any connector (Telegram, Discord,
web chat, etc.) can use to forward non-command messages to a backend.
The backend could be an LLM (Claude Code), a human operator, or any
other service that accepts text and returns text.

The backend reads its configuration from the shared ``agent`` section
in ``hort-config.yaml`` (see :mod:`hort.agent`).  By default, Claude
Code runs inside a hardened Docker container with ``--allowedTools``
instead of ``--dangerously-skip-permissions``.

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
from pathlib import Path
from typing import Any, Callable, Coroutine

from hort.agent import AgentConfig, get_agent_config

logger = logging.getLogger(__name__)


_KEY_REFRESH_INTERVAL = 300  # refresh API key every 5 minutes
_last_key_refresh = 0.0
_cached_api_key = ""


def _get_claude_api_key(force: bool = False) -> str:
    """Get a Claude API key or OAuth token for container injection.

    Tries ANTHROPIC_API_KEY env var first, then OS credential store (OAuth).
    Caches the key and refreshes every 5 minutes (or on force=True).
    """
    global _last_key_refresh, _cached_api_key
    import time as _time

    now = _time.monotonic()
    if not force and _cached_api_key and (now - _last_key_refresh) < _KEY_REFRESH_INTERVAL:
        return _cached_api_key

    try:
        from hort.ext.claude_auth import get_api_key
        key = get_api_key()
        if key:
            _cached_api_key = key
            _last_key_refresh = now
            return key
    except Exception as exc:
        logger.warning("Could not get Claude credentials: %s", exc)

    return _cached_api_key or ""


def is_auth_error(text: str) -> bool:
    """Detect API authentication errors in response text."""
    return any(m in text for m in (
        "authentication_error", "Invalid API key", "invalid_api_key",
        "Invalid authentication credentials", "Failed to authenticate",
    ))


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
    "You are a helpful assistant connected to the user's machine through OpenHORT. "
    "You run in an isolated container — you have NO direct access to the host OS, "
    "no shell commands, no filesystem. Everything you know about the user's machine "
    "comes from the MCP tools provided to you.\n\n"
    "ALWAYS use MCP tools to answer questions. Never say you can't help when "
    "a tool exists. Never suggest the user run commands themselves.\n\n"
    "If a tool failed earlier in this conversation, ALWAYS retry it — tools can "
    "recover at any time (server restart, device reconnect). Never assume a tool "
    "is permanently broken based on past failures.\n\n"
    "When reporting system info, give concrete numbers from the tool data. "
    "Don't speculate or add disclaimers — just report what the tools return."
)

def _build_append_prompt() -> str:
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"Current time: {now}. "
        "IMPORTANT: This is a mobile messaging chat. "
        "NEVER use markdown: no **, no `, no #, no bullet points with -. "
        "Use plain text only. Keep responses short — give the data, skip filler. "
        "When you receive screenshot data from tools, describe what you see "
        "in words — never include raw base64 data in your response. "
        "Tool results include timestamps. If the user asks about the CURRENT state, "
        "always take a fresh screenshot — never reuse one older than 30 seconds."
    )


class MCPBridgeProcess:
    """Manages the MCP bridge SSE server subprocess."""

    def __init__(self, port: int = 0) -> None:
        self._port = port
        self._proc: subprocess.Popen[bytes] | None = None
        self._actual_port: int = 0
        self._mcp_config_path: str = ""
        self._skills_path: str = ""

    @property
    def port(self) -> int:
        return self._actual_port

    @property
    def url(self) -> str:
        return f"http://localhost:{self._actual_port}/sse"

    _host_ipv4: str = ""

    def container_url(self) -> str:
        """URL reachable from inside a Docker container.

        Resolves host.docker.internal to IPv4 once, then caches. Docker's
        IPv6 bridge networking doesn't work and Claude Code's Node.js MCP
        client tries IPv6 first without fallback — so we must use IPv4.
        """
        if not MCPBridgeProcess._host_ipv4:
            try:
                result = subprocess.run(
                    ["docker", "run", "--rm", "--entrypoint", "sh",
                     "openhort-sandbox-base:latest", "-c",
                     "getent ahosts host.docker.internal | head -1 | cut -d' ' -f1"],
                    capture_output=True, text=True, timeout=10,
                )
                ip = result.stdout.strip()
                if ip and ":" not in ip:  # must be IPv4
                    MCPBridgeProcess._host_ipv4 = ip
            except Exception:
                pass
            if not MCPBridgeProcess._host_ipv4:
                MCPBridgeProcess._host_ipv4 = "host.docker.internal"  # fallback
            logger.info("Docker host IPv4: %s", MCPBridgeProcess._host_ipv4)
        return f"http://{MCPBridgeProcess._host_ipv4}:{self._actual_port}/sse"

    @property
    def mcp_config_path(self) -> str:
        return self._mcp_config_path

    @property
    def skills_path(self) -> str:
        return self._skills_path

    def load_skills(self) -> list[Any]:
        """Load skills from the bridge's skills manifest."""
        if not self._skills_path or not os.path.exists(self._skills_path):
            return []
        with open(self._skills_path) as f:
            return json.load(f)

    def ensure_alive(self) -> None:
        """Restart bridge if it died."""
        if self._proc and self._proc.poll() is not None:
            logger.warning("MCP bridge process died (exit=%d), restarting", self._proc.returncode)
            self._proc = None
            self.start()

    def start(self) -> None:
        """Start the MCP bridge SSE server."""
        if self._proc and self._proc.poll() is None:
            return

        self._proc = subprocess.Popen(
            ["python", "-m", "hort.mcp.proxy_bridge", "--sse", "--port", str(self._port)],
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
            elif "Skills manifest:" in text:
                self._skills_path = text.rsplit("Skills manifest: ", 1)[1]
            if self._actual_port and ("SSE server:" in text or "Container URL:" in text):
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
        logger.info("MCP bridge started on port %d, config: %s, skills: %s",
                     self._actual_port, path, self._skills_path or "(none)")

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


def _build_claude_cmd(
    agent_cfg: AgentConfig,
    mcp_config_path: str,
    system_prompt: str,
    session_id: str | None,
    message: str,
) -> list[str]:
    """Build the ``claude`` CLI command from an AgentConfig.

    When ``dangerous_mode`` is off, uses ``--allowedTools`` to
    pre-approve specific tools instead of skipping all permission
    checks.  This is the secure default.
    """
    cmd = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--verbose",
    ]

    if agent_cfg.dangerous_mode:
        cmd.append("--dangerously-skip-permissions")
    elif agent_cfg.allowed_tools:
        cmd.extend(["--allowedTools", ",".join(agent_cfg.allowed_tools)])

    if agent_cfg.container:
        cmd.append("--bare")
        # --bare disables keychain reads, so auth goes through apiKeyHelper
        # in settings.json (written by _get_or_create_container)
        cmd.extend(["--settings", "/workspace/.claude/settings.json"])

    if agent_cfg.model:
        cmd.extend(["--model", agent_cfg.model])

    if session_id:
        cmd.extend(["--resume", session_id])
    elif system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    if mcp_config_path:
        cmd.extend(["--mcp-config", mcp_config_path])

    if agent_cfg.max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(agent_cfg.max_budget_usd)])

    cmd.extend(["--append-system-prompt", _build_append_prompt()])
    # Message MUST come after -- separator because --mcp-config accepts
    # variadic args and would consume the message as a config file path
    cmd.append("--")
    cmd.append(message)
    return cmd


class ChatSession:
    """Per-user Claude Code conversation session.

    Sends messages to Claude Code CLI and parses the stream-json output.
    Supports both host-mode (direct subprocess) and container-mode
    (Docker exec inside a hardened sandbox session).
    """

    def __init__(
        self,
        agent_cfg: AgentConfig,
        mcp_config_path: str,
        system_prompt: str,
        container_session: Any | None = None,
        progress_interval: float = 8.0,
    ) -> None:
        self._agent_cfg = agent_cfg
        self._mcp_config = mcp_config_path
        self._system_prompt = system_prompt
        self._container_session = container_session  # hort.sandbox.Session
        self._session_id: str | None = None
        self._lock = asyncio.Lock()
        self._progress_interval = progress_interval

    async def send(
        self,
        message: str,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """Send a message and return the response text.

        On auth errors, silently refreshes credentials and retries once.
        The user never sees credential errors.
        """
        async with self._lock:
            result = await self._run(message, on_progress)
            if is_auth_error(result):
                logger.warning("Auth error on first attempt — refreshing and retrying")
                new_key = _get_claude_api_key(force=True)
                if new_key and self._container_session:
                    try:
                        self._container_session.write_file("/workspace/.claude/api_key", new_key)
                        logger.info("API key refreshed in container — retrying message")
                    except Exception:
                        pass
                result = await self._run(message, on_progress)
                if is_auth_error(result):
                    return "Something went wrong. Try again."
            return result

    async def _run(
        self,
        message: str,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        cmd = _build_claude_cmd(
            self._agent_cfg,
            self._mcp_config,
            self._system_prompt,
            self._session_id,
            message,
        )

        logger.info("Chat backend: starting claude process (container=%s)",
                     self._container_session is not None)

        if self._container_session is not None:
            proc = await self._container_session.exec_async(cmd)
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=10 * 1024 * 1024,
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
        text = re.sub(r'(?:/9j/|iVBOR)[A-Za-z0-9+/=\n]{200,}', '[image data removed]', text)
        if len(text) > 8000:
            text = text[:8000]

        return text or "(no response)"

    async def send_debug(self, message: str) -> dict[str, Any]:
        """Send a message and return full debug trace — tools, events, timing, exit code.

        Used by the wire.debug WS command and /api/debug/chat REST endpoint.
        Does NOT sanitize errors — returns raw data for debugging.
        """
        async with self._lock:
            return await self._run_debug(message)

    async def _run_debug(self, message: str) -> dict[str, Any]:
        """Run Claude with full event capture for debugging."""
        cmd = _build_claude_cmd(
            self._agent_cfg,
            self._mcp_config,
            self._system_prompt,
            self._session_id,
            message,
        )

        if self._container_session is not None:
            proc = await self._container_session.exec_async(cmd)
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=10 * 1024 * 1024,
            )
        assert proc.stdout is not None

        events: list[dict[str, Any]] = []
        tools: list[dict[str, Any]] = []
        result_text = ""
        start = time.monotonic()

        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            try:
                event = json.loads(line.decode("utf-8", errors="replace").strip())
            except (json.JSONDecodeError, ValueError):
                continue

            etype = event.get("type")
            ts = round(time.monotonic() - start, 2)

            if etype == "system" and event.get("subtype") == "init":
                self._session_id = event.get("session_id")
                events.append({"ts": ts, "type": "init", "session_id": self._session_id})

            elif etype == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "tool_use":
                        name = block.get("name", "")
                        short = name.split("__")[-1] if "__" in name else name
                        tool_input = block.get("input", {})
                        tools.append({"name": short, "full_name": name, "input": tool_input, "ts": ts})
                        events.append({"ts": ts, "type": "tool_call", "tool": short, "input": tool_input})
                    elif block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            events.append({"ts": ts, "type": "text", "text": text[:500]})

            elif etype == "result":
                result_text = event.get("result", "")
                cost = event.get("cost_usd", 0)
                events.append({"ts": ts, "type": "result", "text_len": len(result_text), "cost_usd": cost})
                if not self._session_id:
                    self._session_id = event.get("session_id")

        exit_code = await proc.wait()
        elapsed = round(time.monotonic() - start, 2)

        # Strip base64 blobs from result for readability
        clean = re.sub(r'(?:/9j/|iVBOR|UklGR)[A-Za-z0-9+/=\n]{100,}', '[image_data]', result_text)
        if len(clean) > 4000:
            clean = clean[:4000] + "..."

        return {
            "result": clean.strip(),
            "exit_code": exit_code,
            "elapsed_s": elapsed,
            "tools": tools,
            "events": events,
            "session_id": self._session_id,
        }

    def reset(self) -> None:
        """Reset the session — next message starts a new conversation.

        Also clears Claude's session data inside the container so
        it doesn't auto-load stale project context.
        """
        self._session_id = None
        if self._container_session:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._clear_container_sessions())
            except Exception:
                pass

    async def _clear_container_sessions(self) -> None:
        """Remove Claude session files inside the container."""
        if not self._container_session:
            return
        try:
            await self._container_session.exec_async([
                "sh", "-c", "rm -rf /workspace/.claude/projects/*/sessions/* 2>/dev/null; true"
            ])
        except Exception:
            pass


_shared_manager: "ChatBackendManager | None" = None


def get_llm_executor() -> Any:
    """Get the configured LLM executor llming.

    Looks up the LLM provider from AgentConfig.provider (e.g. "claude-code")
    in the llming registry and returns the LlmExecutor instance.

    This is the preferred entry point for connectors. Call
    ``await executor.execute_power("send_message", {...})`` to chat.
    """
    from hort.commands._registry import get_llming_registry

    registry = get_llming_registry()
    if registry is None:
        return None

    from hort.agent import get_agent_config
    provider = get_agent_config().provider

    # Try exact match first, then with common naming patterns
    for name in (provider, provider.replace("-", "_"), provider.replace("_", "-")):
        inst = registry.get_instance(name)
        if inst is not None:
            return inst

    return None


def get_chat_manager() -> "ChatBackendManager":
    """Get the shared ChatBackendManager singleton.

    DEPRECATED: Use get_llm_executor() instead for provider-agnostic access.
    Kept for backward compatibility with connectors that haven't migrated.
    """
    global _shared_manager
    if _shared_manager is None:
        from hort.agent import get_agent_config
        _shared_manager = ChatBackendManager(agent_cfg=get_agent_config())
        _shared_manager.start()
    return _shared_manager


class ChatBackendManager:
    """Manages chat sessions for all users of a connector.

    Any connector can use this to route non-command messages to Claude Code.
    The MCP bridge provides access to all llming MCP tools.
    The system prompt is built dynamically from extension skills.

    Reads the shared ``agent`` config from ``hort-config.yaml`` so all
    connectors use the same agent settings.  Override with explicit
    ``agent_cfg`` to customise per-connector.
    """

    def __init__(
        self,
        agent_cfg: AgentConfig | None = None,
        system_prompt: str = "",
    ) -> None:
        self._agent_cfg = agent_cfg or get_agent_config()
        self._base_prompt = system_prompt or self._agent_cfg.system_prompt
        self._bridge = MCPBridgeProcess(port=0)
        self._sessions: dict[str, ChatSession] = {}
        self._system_prompt: str = ""
        self._disabled_tools: list[str] = []
        # Container sessions keyed by user_id (only when container mode)
        self._container_sessions: dict[str, Any] = {}
        self._session_manager: Any = None  # hort.sandbox.SessionManager

    @property
    def agent_cfg(self) -> AgentConfig:
        return self._agent_cfg

    def start(self) -> None:
        """Start the MCP bridge and build the system prompt from skills."""
        self._bridge.start()
        self._build_prompt()
        if self._agent_cfg.container:
            self._init_container_backend()

    def _init_container_backend(self) -> None:
        """Ensure the container image is built and session manager ready."""
        from hort.sandbox import SessionManager

        self._session_manager = SessionManager()
        self._session_manager.ensure_base_image()
        image = self._agent_cfg.image
        if not self._session_manager.image_ready(image):
            dockerfile_dir = str(
                Path(__file__).resolve().parent.parent.parent
                / "llmings" / "llms" / "claude_code"
            )
            self._session_manager.build_image(image, dockerfile_dir)
        logger.info("Container backend ready (image=%s)", image)

    def _build_prompt(self) -> None:
        """Build the system prompt dynamically from all llming SOULs.

        Fetches SOUL texts from the main server (all llmings) and
        appends them to the base prompt. No hardcoded tool mentions.
        """
        base = self._base_prompt or DEFAULT_SYSTEM_PROMPT
        parts = [base]

        # Inject SOULs from all llmings (direct registry access, no HTTP)
        try:
            from hort.llming.base import Llming
            from hort.commands._registry import get_llming_registry
            registry = get_llming_registry()
            if registry:
                soul_count = 0
                for name, inst in registry._instances.items():
                    if isinstance(inst, Llming) and inst.soul:
                        parts.append(f"\n--- {name} ---\n{inst.soul}")
                        soul_count += 1
                logger.info("System prompt: %d llming SOULs injected", soul_count)
        except Exception as exc:
            logger.warning("Could not load SOULs: %s", exc)

        # Also load SOUL.md sections from manifest (legacy path)
        try:
            from hort.ext.skills import SoulSection, build_system_prompt
            raw_data = self._bridge.load_skills()
            all_preambles: list[str] = []
            all_sections: list[Any] = []
            for soul in raw_data:
                if soul.get("preamble"):
                    all_preambles.append(soul["preamble"])
                for sec in soul.get("sections", []):
                    all_sections.append(SoulSection(**sec))
            if all_preambles or all_sections:
                combined = "\n\n".join(all_preambles)
                base_with_souls = "\n\n".join(parts)
                self._system_prompt, self._disabled_tools = build_system_prompt(
                    combined, all_sections, base_prompt=base_with_souls,
                )
                logger.info("System prompt built: %d sections, %d chars",
                            len(all_sections), len(self._system_prompt))
                return
        except Exception:
            pass

        self._system_prompt = "\n\n".join(parts)
        self._disabled_tools = []
        logger.info("System prompt built: %d chars", len(self._system_prompt))

    def stop(self) -> None:
        """Stop the MCP bridge, destroy container sessions, clear state."""
        self._bridge.stop()
        for session in self._container_sessions.values():
            try:
                session.destroy()
            except Exception as exc:
                logger.warning("Failed to destroy container session: %s", exc)
        self._container_sessions.clear()
        self._sessions.clear()

    @property
    def alive(self) -> bool:
        return self._bridge.alive

    def _get_or_create_container(self, user_id: str) -> Any:
        """Get or create a sandbox container session for a user.

        Reuses existing containers across server restarts: looks up by
        user label first, then by image match, only creates new if needed.
        """
        from hort.sandbox import SessionConfig, SecurityProfile

        # 1. Check in-memory cache (one container shared across all sessions)
        cache_key = f"envoy:{self._agent_cfg.image}"
        if cache_key in self._container_sessions:
            session = self._container_sessions[cache_key]
            try:
                session.exec(["true"])  # health check
                return session
            except Exception:
                logger.info("Stale container, recreating")
                del self._container_sessions[cache_key]

        # 2. Try to find an existing running container (survives server restart)
        # Use image as label — one container per image, shared across all sessions
        label = f"claude:{self._agent_cfg.image}"
        session = self._session_manager.find_running_by_label(label)
        if session:
            logger.info("Reusing existing container %s", session.container_name)
            session.meta.config.secret_env = {"HOME": "/workspace"}
            self._container_sessions[cache_key] = session
            # Re-provision credentials (may have been refreshed)
            self._provision_container(session)
            return session

        # 3. Try to find any running container with the same image (reuse regardless of label)
        session = self._session_manager.find_running(image=self._agent_cfg.image)
        if session:
            logger.info("Reusing container %s by image match", session.container_name)
            session.meta.user_data["label"] = label
            session.meta.config.secret_env = {"HOME": "/workspace"}
            session._save()
            self._container_sessions[cache_key] = session
            self._provision_container(session)
            return session

        # 4. Create new container
        cfg = SessionConfig(
            image=self._agent_cfg.image,
            memory=self._agent_cfg.memory,
            cpus=self._agent_cfg.cpus,
            secret_env={"HOME": "/workspace"},
            security=SecurityProfile(),
        )
        session = self._session_manager.create(cfg)
        session.meta.user_data["label"] = label
        session._save()
        session.start()

        self._provision_container(session)
        self._container_sessions[cache_key] = session
        logger.info("Created container session: %s (image=%s)", session.id, self._agent_cfg.image)
        return session

    def _provision_container(self, session: Any) -> None:
        """Write MCP config and credentials into a container.

        Called on both new containers and reused ones (credentials may
        have been refreshed since the container was created).
        """
        # MCP config pointing to host bridge
        mcp_config = {
            "mcpServers": {
                "openhort": {
                    "type": "sse",
                    "url": self._bridge.container_url(),
                },
            },
        }
        session.write_file(
            "/workspace/.claude-mcp.json",
            json.dumps(mcp_config),
        )

        # API key + settings for Claude Code auth.
        # /home/sandbox is read-only (security layer 7).
        # Write to /workspace, HOME=/workspace set via exec env.
        api_key = _get_claude_api_key()
        if api_key:
            session.exec(["mkdir", "-p", "/workspace/.claude"])
            session.write_file("/workspace/.claude/api_key", api_key)
            session.write_file(
                "/workspace/.claude/settings.json",
                json.dumps({"apiKeyHelper": "cat /workspace/.claude/api_key"}),
            )
            session.write_file("/workspace/.claude.json", "{}")

    def get_session(self, user_id: str) -> ChatSession:
        """Get or create a chat session for a user."""
        old_port = self._bridge.port
        self._bridge.ensure_alive()
        if self._bridge.port != old_port and old_port > 0:
            # Bridge restarted on new port — re-provision all containers
            logger.info("Bridge port changed %d → %d, re-provisioning containers", old_port, self._bridge.port)
            for session in self._container_sessions.values():
                try:
                    self._provision_container(session)
                except Exception:
                    pass
        if user_id not in self._sessions:
            container_session = None
            mcp_config = self._bridge.mcp_config_path

            if self._agent_cfg.container and self._session_manager:
                container_session = self._get_or_create_container(user_id)
                # Container uses the config written inside it
                mcp_config = "/workspace/.claude-mcp.json"

            self._sessions[user_id] = ChatSession(
                agent_cfg=self._agent_cfg,
                mcp_config_path=mcp_config,
                system_prompt=self._system_prompt,
                container_session=container_session,
                progress_interval=self._agent_cfg.progress_interval,
            )
        return self._sessions[user_id]

    def reset_session(self, user_id: str) -> None:
        """Reset a user's session (new conversation)."""
        session = self._sessions.get(user_id)
        if session:
            session.reset()
