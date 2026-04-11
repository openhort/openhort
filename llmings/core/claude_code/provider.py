"""Claude Code executor — LLM llming for Claude Code CLI.

Extends LlmExecutor with Claude Code-specific implementation:
container management, CLI command building, stream-json parsing.

Any connector (Telegram, Wire) or other llming can call the standard
Powers (send_message, reset_session, etc.) without knowing it's Claude.

To create a different LLM executor (e.g. for Codex):
    class CodexExecutor(LlmExecutor):
        provider_name = "codex"
        async def _send(self, session_key, text, system_prompt):
            ...
"""

from __future__ import annotations

import logging
from typing import Any

from hort.llming import LlmExecutor, SendResult

logger = logging.getLogger(__name__)


class ClaudeCodeExecutor(LlmExecutor):
    """Claude Code executor — runs Claude CLI in local or container mode.

    Config (from hort-config.yaml llmings.claude-code.config):
        model: claude-sonnet-4-6
        credentials: keychain
    """

    provider_name = "claude-code"

    _chat_mgr: Any = None  # ChatBackendManager, created on first use
    _started: bool = False

    def activate(self, config: dict[str, Any]) -> None:
        super().activate(config) if hasattr(super(), 'activate') else None
        self._config = config
        self.log.info("Claude Code executor activated (model=%s)", config.get("model", "default"))

    def _ensure_started(self) -> None:
        """Lazily start the Claude backend on first use."""
        if self._started:
            return
        try:
            from hort.agent import get_agent_config
            from hort.ext.chat_backend import ChatBackendManager
            from hort.hort_config import get_hort_config

            agent_cfg = get_agent_config()

            # Apply llming-level config overrides from YAML
            overrides: dict = {}
            if self._config.get("model"):
                overrides["model"] = self._config["model"]

            # Apply envoy container config from YAML
            hort_cfg = get_hort_config()
            llming_cfg = hort_cfg.get_llming("claude-code")
            if llming_cfg and llming_cfg.envoy:
                container_cfg = llming_cfg.envoy.get("container", {})
                if container_cfg.get("image"):
                    overrides["image"] = container_cfg["image"]
                if container_cfg.get("memory"):
                    overrides["memory"] = container_cfg["memory"]
                if container_cfg.get("cpus"):
                    overrides["cpus"] = container_cfg["cpus"]
                overrides["container"] = True

            if overrides:
                agent_cfg = agent_cfg.model_copy(update=overrides)

            self._chat_mgr = ChatBackendManager(agent_cfg=agent_cfg)
            self._chat_mgr.start()
            self._started = True
            self.log.info(
                "Claude backend started (container=%s, image=%s)",
                agent_cfg.container, agent_cfg.image,
            )
            self.vault.set("state", self.get_pulse())
        except Exception:
            self.log.exception("Failed to start Claude backend")

    # ── LlmExecutor interface ──

    async def _send(self, session_key: str, text: str, system_prompt: str) -> SendResult:
        self._ensure_started()
        if not self._chat_mgr:
            return SendResult(text="Claude backend not available.")
        try:
            session = self._chat_mgr.get_session(session_key)
            response = await session.send(text)
            return SendResult(
                text=response,
                provider_session_id=getattr(session, "_session_id", ""),
            )
        except Exception:
            logger.exception("Claude send error for session %s", session_key)
            return SendResult(text="Something went wrong. Try again.")

    async def _on_end_session(self, session_key: str) -> None:
        if self._chat_mgr:
            self._chat_mgr.reset_session(session_key)
        self.vault.set("state", self.get_pulse())

    # ── Pulse (extends base) ──

    def get_pulse(self) -> dict[str, Any]:
        base = super().get_pulse()
        base["started"] = self._started
        base["alive"] = self._chat_mgr.alive if self._chat_mgr else False
        base["model"] = self._config.get("model", "default")
        return base

    # ── Convenience for connectors (delegates to standard Powers) ──

    async def chat(self, session_key: str, text: str, on_progress: Any = None) -> str:
        """Send a message and return response text.

        Creates a session if needed, sends the message via standard
        Powers. Connectors can call this instead of execute_power directly.
        """
        if session_key not in self._sessions:
            await self.execute_power("create_session", {"session_key": session_key})
        result = await self.execute_power("send_message", {"session_key": session_key, "text": text})
        return result.get("text", "Something went wrong. Try again.")

    async def new_session(self, session_key: str) -> None:
        """End current session and start fresh (for /new command)."""
        if session_key in self._sessions:
            await self.execute_power("end_session", {"session_key": session_key})

    # ── Cleanup ──

    def deactivate(self) -> None:
        super().deactivate()
        if self._chat_mgr:
            try:
                self._chat_mgr.stop()
            except Exception:
                pass
        self._started = False
