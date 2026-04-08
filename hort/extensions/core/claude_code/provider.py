"""Claude Code — standard llming plugin with envoy (container execution).

Exposes Claude as a normal plugin with MCP tools (send_message,
get_conversation, reset_session) and manages the chat backend
lifecycle. Telegram, Wire, and any other connector route messages
here through the standard plugin system.

Replaces the special-cased chat_backend integration in individual
connectors with a unified plugin that reads config from hort-config.yaml.
"""

from __future__ import annotations

import logging
from typing import Any

from hort.ext.mcp import MCPMixin
from hort.ext.plugin import PluginBase

logger = logging.getLogger(__name__)


class ClaudeCodePlugin(PluginBase, MCPMixin):
    """Claude Code llming — chat with Claude via any connector.

    Config (from hort-config.yaml llmings.claude.config):
        model: claude-sonnet-4-6
        credentials: keychain
    """

    _chat_mgr: Any = None  # ChatBackendManager, created on first use
    _started: bool = False

    def activate(self, config: dict[str, Any]) -> None:
        """Store config for lazy initialization."""
        self._config = config
        self.log.info("Claude Code plugin activated (model=%s)", config.get("model", "default"))

    def _ensure_started(self) -> None:
        """Lazily create and start the chat backend on first use.

        Reads envoy config from hort-config.yaml to determine container
        settings (image, memory, cpus). Falls back to AgentConfig defaults.
        """
        if self._started:
            return
        try:
            from hort.agent import AgentConfig, get_agent_config
            from hort.ext.chat_backend import ChatBackendManager
            from hort.hort_config import get_hort_config

            agent_cfg = get_agent_config()

            # Apply llming-level config overrides from YAML
            overrides: dict = {}
            if self._config.get("model"):
                overrides["model"] = self._config["model"]

            # Apply envoy container config from YAML
            hort_cfg = get_hort_config()
            llming_cfg = hort_cfg.get_llming("claude")
            if llming_cfg and llming_cfg.envoy:
                container_cfg = llming_cfg.envoy.get("container", {})
                if container_cfg.get("image"):
                    overrides["image"] = container_cfg["image"]
                if container_cfg.get("memory"):
                    overrides["memory"] = container_cfg["memory"]
                if container_cfg.get("cpus"):
                    overrides["cpus"] = container_cfg["cpus"]
                # Envoy defined = container mode
                overrides["container"] = True

            if overrides:
                agent_cfg = agent_cfg.model_copy(update=overrides)

            self._chat_mgr = ChatBackendManager(agent_cfg=agent_cfg)
            self._chat_mgr.start()
            self._started = True
            self.log.info(
                "Chat backend started (container=%s, image=%s, memory=%s)",
                agent_cfg.container, agent_cfg.image, agent_cfg.memory,
            )
        except Exception:
            self.log.exception("Failed to start chat backend")

    def get_status(self) -> dict[str, Any]:
        """Return live status for Cards/Pulse."""
        return {
            "started": self._started,
            "alive": self._chat_mgr.alive if self._chat_mgr else False,
            "model": self._config.get("model", "default"),
            "active_sessions": len(self._chat_mgr._sessions) if self._chat_mgr else 0,
        }

    # ===== MCP Tools (Powers) =====

    def get_mcp_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "send_message",
                "description": "Send a message to Claude and get a response",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string", "description": "Session identifier (user or conversation ID)"},
                        "text": {"type": "string", "description": "Message text"},
                    },
                    "required": ["session_key", "text"],
                },
            },
            {
                "name": "get_session_status",
                "description": "Get status of a chat session",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string"},
                    },
                    "required": ["session_key"],
                },
            },
            {
                "name": "reset_session",
                "description": "Reset a chat session (start fresh conversation)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string"},
                    },
                    "required": ["session_key"],
                },
            },
        ]

    async def execute_mcp_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self._ensure_started()
        if not self._chat_mgr or not self._chat_mgr.alive:
            return {"error": "Chat backend not running"}

        if name == "send_message":
            session = self._chat_mgr.get_session(arguments["session_key"])
            response = await session.send(arguments["text"])
            return {"response": response}

        elif name == "get_session_status":
            key = arguments["session_key"]
            if key in self._chat_mgr._sessions:
                session = self._chat_mgr._sessions[key]
                return {
                    "active": True,
                    "session_id": getattr(session, "_session_id", None),
                }
            return {"active": False}

        elif name == "reset_session":
            self._chat_mgr.reset_session(arguments["session_key"])
            return {"ok": True}

        return {"error": f"Unknown tool: {name}"}

    # ===== Chat Interface (for connectors) =====

    async def chat(self, session_key: str, text: str, on_progress: Any = None) -> str:
        """Send a message and return the response text.

        This is the primary interface connectors use. It manages the
        backend lifecycle and returns clean text (no internal errors).
        """
        self._ensure_started()
        if not self._chat_mgr or not self._chat_mgr.alive:
            return "Chat backend not available."
        try:
            session = self._chat_mgr.get_session(session_key)
            return await session.send(text, on_progress=on_progress)
        except Exception:
            logger.exception("Chat error for session %s", session_key)
            return "Something went wrong. Try again."

    def reset(self, session_key: str) -> None:
        """Reset a session (for /new command)."""
        if self._chat_mgr:
            self._chat_mgr.reset_session(session_key)

    # ===== Cleanup =====

    def deactivate(self) -> None:
        """Stop the chat backend and clean up containers."""
        if self._chat_mgr:
            try:
                self._chat_mgr.stop()
            except Exception:
                pass
        self._started = False
