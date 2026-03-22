"""Openhort WebSocket controller — handles all control-channel messages.

All window operations are routed through the active target's
``PlatformProvider``, so the controller works identically whether
the target is local macOS, a Linux Docker container, or a remote VM.

When the target is ``"all"``, windows from every registered provider
are aggregated into a single list, each tagged with its ``target_id``.
"""

from __future__ import annotations

import base64
from typing import Any

from llming_com import BaseController

from hort.ext.types import PlatformProvider
from hort.models import InputEvent, StreamConfig
from hort.targets import TargetRegistry


class HortController(BaseController):
    """Handles JSON messages on the control WebSocket.

    Message types (client → server):
        list_targets     → targets_list response
        set_target       → target_changed response  (use "all" for flat view)
        list_windows     → windows_list response
        get_thumbnail    → thumbnail response (base64 JPEG)
        get_status       → status response
        get_spaces       → spaces response (workspaces)
        switch_space     → space_switched response
        stream_config    → updates session stream config
        input            → forwards input event to target
        heartbeat        → heartbeat_ack (handled by base)
    """

    def __init__(self, session_id: str, **kwargs: Any) -> None:
        super().__init__(session_id, rate_limit_max=120, **kwargs)
        self._entry: Any = None
        self._target_id: str = "all"  # default: show all targets
        self._cached_window: Any = None  # cached WindowInfo for input
        self._cached_provider: PlatformProvider | None = None  # cached provider for input

    def set_session_entry(self, entry: Any) -> None:
        """Store a reference to the session entry."""
        self._entry = entry

    def _provider(self) -> PlatformProvider | None:
        """Get the active target's provider (None when target is 'all')."""
        if self._target_id == "all":
            return None
        registry = TargetRegistry.get()
        return registry.get_provider(self._target_id)

    def _provider_for_window(self, window_id: int) -> tuple[PlatformProvider | None, str]:
        """Find which provider owns a window_id.

        Returns (provider, target_id).  Checks the active target first,
        then falls back to scanning all targets.
        """
        registry = TargetRegistry.get()

        # If a specific target is set, use it directly
        if self._target_id != "all":
            p = registry.get_provider(self._target_id)
            return p, self._target_id

        # "all" mode: scan all providers for the window
        for info in registry.list_targets():
            p = registry.get_provider(info.id)
            if p is None:
                continue
            for w in p.list_windows():
                if w.window_id == window_id:
                    return p, info.id

        return None, ""

    async def handle_message(self, msg: dict[str, Any]) -> None:  # noqa: C901
        """Route an incoming message to the appropriate handler."""
        msg_type = msg.get("type", "")

        if msg_type == "list_targets":
            await self._handle_list_targets()
        elif msg_type == "set_target":
            await self._handle_set_target(msg)
        elif msg_type == "list_windows":
            await self._handle_list_windows(msg)
        elif msg_type == "get_thumbnail":
            await self._handle_get_thumbnail(msg)
        elif msg_type == "get_status":
            await self._handle_get_status()
        elif msg_type == "get_spaces":
            await self._handle_get_spaces()
        elif msg_type == "switch_space":
            await self._handle_switch_space(msg)
        elif msg_type == "stream_config":
            await self._handle_stream_config(msg)
        elif msg_type == "input":
            await self._handle_input(msg)
        else:
            await super().handle_message(msg)

    # ----- Target management -----

    async def _handle_list_targets(self) -> None:
        registry = TargetRegistry.get()
        targets = registry.list_targets()
        await self.send({
            "type": "targets_list",
            "targets": [
                {"id": t.id, "name": t.name, "provider_type": t.provider_type, "status": t.status}
                for t in targets
            ],
            "active": self._target_id,
        })

    async def _handle_set_target(self, msg: dict[str, Any]) -> None:
        target_id = msg.get("target_id", "")
        registry = TargetRegistry.get()
        if target_id == "all" or registry.get_provider(target_id) is not None:
            self._target_id = target_id
            if self._entry is not None:
                self._entry.stream_config = None
                self._entry.active_window_id = 0
            await self.send({"type": "target_changed", "target_id": target_id})
        else:
            await self.send({"type": "error", "message": f"Unknown target: {target_id}"})

    # ----- Window operations -----

    async def _handle_list_windows(self, msg: dict[str, Any]) -> None:
        registry = TargetRegistry.get()
        app_filter = msg.get("app_filter")

        if self._target_id == "all":
            # Aggregate from all targets, tag each window
            all_win: list[dict[str, Any]] = []
            all_names: set[str] = set()
            for info in registry.list_targets():
                p = registry.get_provider(info.id)
                if p is None:
                    continue
                windows = p.list_windows(app_filter)
                unfiltered = p.list_windows() if app_filter else windows
                all_names.update(w.owner_name for w in unfiltered)
                for w in windows:
                    d = w.model_dump()
                    d["target_id"] = info.id
                    d["target_name"] = info.name
                    all_win.append(d)
            await self.send({
                "type": "windows_list",
                "windows": all_win,
                "app_names": sorted(all_names),
            })
        else:
            provider = self._provider()
            if provider is None:
                await self.send({"type": "windows_list", "windows": [], "app_names": []})
                return
            windows = provider.list_windows(app_filter)
            unfiltered = provider.list_windows() if app_filter else windows
            app_names = sorted({w.owner_name for w in unfiltered})
            win_dicts = []
            target_info = registry.get_info(self._target_id)
            for w in windows:
                d = w.model_dump()
                d["target_id"] = self._target_id
                d["target_name"] = target_info.name if target_info else self._target_id
                win_dicts.append(d)
            await self.send({
                "type": "windows_list",
                "windows": win_dicts,
                "app_names": app_names,
            })

    async def _handle_get_thumbnail(self, msg: dict[str, Any]) -> None:
        window_id = msg.get("window_id", 0)
        target_id = msg.get("target_id", "")

        # If target_id provided, use that provider directly
        if target_id:
            provider = TargetRegistry.get().get_provider(target_id)
        else:
            provider, _ = self._provider_for_window(window_id)

        jpeg = provider.capture_window(window_id, max_width=400, quality=50) if provider else None
        if jpeg is not None:
            await self.send({
                "type": "thumbnail",
                "window_id": window_id,
                "data": base64.b64encode(jpeg).decode("ascii"),
            })
        else:
            await self.send({
                "type": "thumbnail",
                "window_id": window_id,
                "data": None,
            })

    async def _handle_get_status(self) -> None:
        from hort.session import HortRegistry

        registry: HortRegistry = HortRegistry.get()  # type: ignore[assignment]
        await self.send({
            "type": "status",
            "observers": registry.observer_count(),
            "version": "0.1.0",
        })

    async def _handle_get_spaces(self) -> None:
        provider = self._provider()
        if provider is None:
            await self.send({"type": "spaces", "spaces": [], "current": 1, "count": 0})
            return
        workspaces = provider.get_workspaces()
        await self.send({
            "type": "spaces",
            "spaces": [
                {"index": ws.index, "is_current": ws.is_current}
                for ws in workspaces
            ],
            "current": provider.get_current_index(),
            "count": len(workspaces),
        })

    async def _handle_switch_space(self, msg: dict[str, Any]) -> None:
        provider = self._provider()
        index = msg.get("index", 0)
        ok = provider.switch_to(index) if provider else False
        await self.send({"type": "space_switched", "ok": ok, "target": index})

    async def _handle_stream_config(self, msg: dict[str, Any]) -> None:
        try:
            data = {k: v for k, v in msg.items() if k != "type"}
            # Client may send target_id to route the stream to the right provider
            target_id = data.pop("target_id", "")
            config = StreamConfig(**data)
            if self._entry is not None:
                self._entry.stream_config = config
                self._entry.active_window_id = config.window_id
                # Resolve which target owns this window
                if target_id:
                    self._entry.active_target_id = target_id
                elif self._target_id != "all":
                    self._entry.active_target_id = self._target_id
                else:
                    _, resolved = self._provider_for_window(config.window_id)
                    self._entry.active_target_id = resolved
                # Cache provider + window so input doesn't call list_windows per keystroke
                p = self._provider() if self._target_id != "all" else (
                    TargetRegistry.get().get_provider(self._entry.active_target_id)
                )
                self._cached_provider = p
                if p:
                    wins = p.list_windows()
                    self._cached_window = next(
                        (w for w in wins if w.window_id == config.window_id), None
                    )
            await self.send({"type": "stream_config_ack", "window_id": config.window_id})
        except Exception:
            await self.send({"type": "error", "message": "Invalid stream config"})

    async def _handle_input(self, msg: dict[str, Any]) -> None:
        try:
            win = self._cached_window
            provider = self._cached_provider
            if win is None or provider is None:
                return
            event_data: dict[str, Any] = {
                k: v for k, v in msg.items() if k != "type"
            }
            if "event_type" in event_data:
                event_data["type"] = event_data.pop("event_type")
            event = InputEvent(**event_data)
            provider.handle_input(event, win.bounds, pid=win.owner_pid)
        except Exception:
            pass
