"""Clipboard History plugin — tracks clipboard changes with searchable history."""

from __future__ import annotations

import hashlib
import subprocess
import time
from typing import Any

from hort.llming import Llming, Power, PowerType


class ClipboardHistory(Llming):
    """Polls the system clipboard and stores unique entries for search and review."""

    def activate(self, config: dict[str, Any]) -> None:
        self._last_hash: str = ""
        self._clips: list[dict[str, Any]] = []
        self.log.info("Clipboard history activated")

    def deactivate(self) -> None:
        self.log.info("Clipboard history deactivated")

    def get_pulse(self) -> dict[str, Any]:
        """Return in-memory clipboard data."""
        return {"clips": self._clips[-20:]}

    # ===== Scheduler =====

    def poll_clipboard(self) -> None:
        """Polls the macOS clipboard via pbpaste. Runs in executor thread."""
        if not self.config.get("auto_capture", True):
            return

        try:
            result = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            self.log.debug("pbpaste failed: %s", e)
            return

        if not text or not text.strip():
            return

        text_hash = hashlib.sha256(text.encode()).hexdigest()
        if text_hash == self._last_hash:
            return

        self._last_hash = text_hash

        # Cache in memory
        ts = int(time.time() * 1000)
        entry = {
            "text": text,
            "hash": text_hash,
            "timestamp": ts,
            "length": len(text),
        }
        self._clips.append(entry)
        if len(self._clips) > 100:
            self._clips = self._clips[-100:]
        self.vault.set("state", {"clips": self._clips[-20:]})

        # Persist to disk (clipboard is persistent data)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._store_clip(entry))
        finally:
            loop.close()

    async def _store_clip(self, entry: dict[str, Any]) -> None:
        """Store a clipboard entry in vault."""
        self.vault.insert("clips", entry, ttl=86400)

    # ===== Powers =====

    def get_powers(self) -> list[Power]:
        return [
            # MCP tools
            Power(
                name="search_clipboard",
                type=PowerType.MCP,
                description="Search text in recent clipboard entries",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text to search for in clipboard entries",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Power(
                name="get_clipboard_history",
                type=PowerType.MCP,
                description="List recent clipboard entries",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Max entries to return",
                            "default": 20,
                        },
                    },
                },
            ),
            # Connector commands
            Power(
                name="clipboard",
                type=PowerType.COMMAND,
                description="Recent clipboard entries",
            ),
            Power(
                name="clip_search",
                type=PowerType.COMMAND,
                description="Search clipboard",
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        # MCP: search_clipboard
        if name == "search_clipboard":
            query = args.get("query", "")
            if not query:
                return {
                    "content": [{"type": "text", "text": "Query is required"}],
                    "is_error": True,
                }
            matches = []
            query_lower = query.lower()
            for entry in reversed(self._clips):
                if query_lower in entry.get("text", "").lower():
                    matches.append(entry)
                    if len(matches) >= 20:
                        break
            if not matches:
                return {"content": [{"type": "text", "text": f"No clipboard entries matching '{query}'"}]}
            lines = [f"Found {len(matches)} matching entries:"]
            for e in matches:
                ts = e.get("timestamp", 0)
                ts_str = time.strftime("%H:%M:%S", time.localtime(ts / 1000))
                preview = e.get("text", "")[:100]
                lines.append(f"  [{ts_str}] {preview}")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        # MCP: get_clipboard_history
        if name == "get_clipboard_history":
            limit = args.get("limit", 20)
            entries = list(reversed(self._clips[-limit:]))
            if not entries:
                return {"content": [{"type": "text", "text": "No clipboard history available yet"}]}
            lines = [f"{len(entries)} recent clipboard entries:"]
            for e in entries:
                ts = e.get("timestamp", 0)
                ts_str = time.strftime("%H:%M:%S", time.localtime(ts / 1000))
                preview = e.get("text", "")[:100]
                lines.append(f"  [{ts_str}] ({e.get('length', 0)} chars) {preview}")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        # Command: clipboard
        if name == "clipboard":
            entries = list(reversed(self._clips[-5:]))
            if not entries:
                return "No clipboard history yet."
            lines = []
            for e in entries:
                ts = e.get("timestamp", 0)
                ts_str = time.strftime("%H:%M:%S", time.localtime(ts / 1000))
                preview = e.get("text", "")[:100]
                lines.append(f"[{ts_str}] {preview}")
            return "\n".join(lines)

        # Command: clip_search
        if name == "clip_search":
            query = args.get("args", "").strip()
            if not query:
                return "Usage: /clip_search <text>"
            query_lower = query.lower()
            matches = []
            for entry in reversed(self._clips):
                if query_lower in entry.get("text", "").lower():
                    matches.append(entry)
                    if len(matches) >= 10:
                        break
            if not matches:
                return f"No clipboard entries matching '{query}'."
            lines = [f"Found {len(matches)} match(es):"]
            for e in matches:
                ts = e.get("timestamp", 0)
                ts_str = time.strftime("%H:%M:%S", time.localtime(ts / 1000))
                preview = e.get("text", "")[:100]
                lines.append(f"[{ts_str}] {preview}")
            return "\n".join(lines)

        return {"error": f"Unknown power: {name}"}
