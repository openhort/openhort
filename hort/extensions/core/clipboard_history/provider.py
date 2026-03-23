"""Clipboard History plugin — tracks clipboard changes with searchable history."""

from __future__ import annotations

import hashlib
import subprocess
import time
from typing import Any

from hort.ext.mcp import MCPMixin, MCPToolDef, MCPToolResult
from hort.ext.plugin import PluginBase
from hort.ext.scheduler import ScheduledMixin


class ClipboardHistory(PluginBase, ScheduledMixin, MCPMixin):
    """Polls the system clipboard and stores unique entries for search and review."""

    def activate(self, config: dict[str, Any]) -> None:
        self._last_hash: str = ""
        self._clips: list[dict[str, Any]] = []
        self.log.info("Clipboard history activated")

    def deactivate(self) -> None:
        self.log.info("Clipboard history deactivated")

    def get_status(self) -> dict[str, Any]:
        """Return in-memory clipboard data."""
        return {"clips": self._clips[-20:]}

    # ===== Scheduler =====

    def poll_clipboard(self) -> None:
        """Polls the macOS clipboard via pbpaste. Runs in executor thread."""
        if not self.config.is_feature_enabled("auto_capture"):
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

        # Persist to disk (clipboard is persistent data)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._store_clip(entry))
        finally:
            loop.close()

    async def _store_clip(self, entry: dict[str, Any]) -> None:
        """Store a clipboard entry and enforce the max 100 entry limit."""
        ts = entry["timestamp"]
        await self.store.put(f"clip:{ts}", entry, ttl_seconds=86400)

        # Enforce max 100 entries — remove oldest if over limit
        keys = await self.store.list_keys("clip:")
        if len(keys) > 100:
            keys.sort()
            for old_key in keys[: len(keys) - 100]:
                await self.store.delete(old_key)

    # ===== MCP =====

    def get_mcp_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="search_clipboard",
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
            MCPToolDef(
                name="get_clipboard_history",
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
        ]

    async def execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        if tool_name == "search_clipboard":
            query = arguments.get("query", "")
            if not query:
                return MCPToolResult(
                    content=[{"type": "text", "text": "Query is required"}],
                    is_error=True,
                )
            matches = []
            query_lower = query.lower()
            for entry in reversed(self._clips):
                if query_lower in entry.get("text", "").lower():
                    matches.append(entry)
                    if len(matches) >= 20:
                        break
            if not matches:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"No clipboard entries matching '{query}'"}]
                )
            lines = [f"Found {len(matches)} matching entries:"]
            for e in matches:
                ts = e.get("timestamp", 0)
                ts_str = time.strftime("%H:%M:%S", time.localtime(ts / 1000))
                preview = e.get("text", "")[:100]
                lines.append(f"  [{ts_str}] {preview}")
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])

        elif tool_name == "get_clipboard_history":
            limit = arguments.get("limit", 20)
            entries = list(reversed(self._clips[-limit:]))
            if not entries:
                return MCPToolResult(
                    content=[{"type": "text", "text": "No clipboard history available yet"}]
                )
            lines = [f"{len(entries)} recent clipboard entries:"]
            for e in entries:
                ts = e.get("timestamp", 0)
                ts_str = time.strftime("%H:%M:%S", time.localtime(ts / 1000))
                preview = e.get("text", "")[:100]
                lines.append(f"  [{ts_str}] ({e.get('length', 0)} chars) {preview}")
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])

        return MCPToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            is_error=True,
        )
