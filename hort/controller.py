"""Openhort WebSocket controller — handles all control-channel messages.

All window operations are routed through the active target's
``PlatformProvider``, so the controller works identically whether
the target is local macOS, a Linux Docker container, or a remote VM.

When the target is ``"all"``, windows from every registered provider
are aggregated into a single list, each tagged with its ``target_id``.

**IMPORTANT:** Every provider call (list_windows, capture_window, handle_input,
etc.) runs in a thread executor via ``_run_sync`` so it never blocks the
async event loop.  Provider implementations may use subprocess, docker exec,
or other blocking I/O — none of that touches the main thread.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time as _time
from typing import Any

logger = logging.getLogger("hort.controller")

from llming_com import BaseController

from hort.ext.types import PlatformProvider
from hort.models import InputEvent, StreamConfig
from hort.targets import TargetRegistry


async def _run_sync(fn: Any, *args: Any) -> Any:
    """Run a synchronous function in the default executor (thread pool)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


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
        terminal_spawn   → terminal_spawned response
        terminal_list    → terminal_list response
        terminal_close   → terminal_closed response
        terminal_resize  → (no response)
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

    # Legacy message types → handler method names (flat, no namespace).
    # New features use WSRouter with dot-namespaced types instead.
    _HANDLERS: dict[str, str] = {
        "list_targets": "_handle_list_targets",
        "set_target": "_handle_set_target",
        "list_windows": "_handle_list_windows",
        "get_thumbnail": "_handle_get_thumbnail",
        "subscribe_thumbnails": "_handle_subscribe_thumbnails",
        "get_status": "_handle_get_status",
        "get_spaces": "_handle_get_spaces",
        "switch_space": "_handle_switch_space",
        "stream_config": "_handle_stream_config",
        "stream_ack": "_handle_stream_ack",
        "stream_stop": "_handle_stream_stop",
        "input": "_handle_input",
        "terminal_spawn": "_handle_terminal_spawn",
        "terminal_list": "_handle_terminal_list",
        "terminal_close": "_handle_terminal_close",
        "terminal_resize": "_handle_terminal_resize",
        "token_create": "_handle_token_create",
        "token_list": "_handle_token_list",
        "token_verify": "_handle_token_verify",
        "token_revoke": "_handle_token_revoke",
        "tunnel_status": "_handle_tunnel_status",
        "camera_offer": "_handle_camera_offer",
        "camera_stop": "_handle_camera_stop",
    }

    async def handle_message(self, msg: dict[str, Any]) -> None:
        """Route a message: legacy dict → WSRouter (namespaced) → base."""
        msg_type = msg.get("type", "")
        t0 = _time.monotonic()

        # 1. Legacy flat handlers (stream, input, terminals, tokens)
        handler_name = self._HANDLERS.get(msg_type)
        if handler_name:
            # stream_ack is high-frequency (15+ fps) — skip rate limiting
            if msg_type not in ("stream_ack", "heartbeat") and not self.check_rate_limit():
                return
            handler = getattr(self, handler_name, None)
            if handler is None:
                logger.error("Handler %s not found on controller", handler_name)
                return
            import inspect
            if "msg" in inspect.signature(handler).parameters:
                await handler(msg)
            else:
                await handler()
        else:
            # 2. WSRouter dispatch (namespaced: llmings.list, config.get, etc.)
            # 3. Falls through to BaseController.handle_message → heartbeat
            await super().handle_message(msg)

        elapsed = (_time.monotonic() - t0) * 1000
        if elapsed > 200:
            logger.warning("Slow message: %s took %.0fms", msg_type, elapsed)

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
            self._cached_window = None
            self._cached_provider = None
            await self.send({"type": "target_changed", "target_id": target_id})
        else:
            await self.send({"type": "error", "message": f"Unknown target: {target_id}"})

    # ----- Window operations (all provider calls in executor) -----

    async def _handle_list_windows(self, msg: dict[str, Any]) -> None:
        registry = TargetRegistry.get()
        app_filter = msg.get("app_filter")

        if self._target_id == "all":
            # Fetch from all providers in PARALLEL — never sequential
            targets = [
                (info, registry.get_provider(info.id))
                for info in registry.list_targets()
            ]
            targets = [(info, p) for info, p in targets if p is not None]

            async def _fetch(info: Any, p: Any) -> tuple[Any, list[Any], list[Any]]:
                windows = await _run_sync(p.list_windows, app_filter)
                unfiltered = (await _run_sync(p.list_windows)) if app_filter else windows
                return info, windows, unfiltered

            results = await asyncio.gather(
                *[_fetch(info, p) for info, p in targets],
                return_exceptions=True,
            )

            all_win: list[dict[str, Any]] = []
            all_names: set[str] = set()
            for result in results:
                if isinstance(result, Exception):  # pragma: no cover
                    continue
                info, windows, unfiltered = result
                all_names.update(w.owner_name for w in unfiltered)
                for w in windows:
                    d = w.model_dump()
                    d["target_id"] = info.id
                    d["target_name"] = info.name
                    all_win.append(d)

            # Feed the thumbnail scheduler (windows only, not screens)
            from hort.thumbnailer import ThumbnailScheduler
            ThumbnailScheduler.get().set_windows([w for w in all_win if w.get("source_type") != "screen"])

            # UI gets windows only (screens filtered out — Desktop not in picker grid)
            ui_windows = [w for w in all_win if w.get("source_type") != "screen"]
            await self.send({
                "type": "windows_list",
                "windows": ui_windows,
                "app_names": sorted(all_names),
            })
        else:
            provider = self._provider()
            if provider is None:
                await self.send({"type": "windows_list", "windows": [], "app_names": []})
                return
            windows = await _run_sync(provider.list_windows, app_filter)
            unfiltered = (await _run_sync(provider.list_windows)) if app_filter else windows
            app_names = sorted({w.owner_name for w in unfiltered})
            win_dicts = []
            target_info = registry.get_info(self._target_id)
            for w in windows:
                d = w.model_dump()
                d["target_id"] = self._target_id
                d["target_name"] = target_info.name if target_info else self._target_id
                win_dicts.append(d)
            # Feed the thumbnail scheduler (windows only)
            from hort.thumbnailer import ThumbnailScheduler
            ThumbnailScheduler.get().set_windows([w for w in win_dicts if w.get("source_type") != "screen"])

            ui_windows = [w for w in win_dicts if w.get("source_type") != "screen"]
            await self.send({
                "type": "windows_list",
                "windows": ui_windows,
                "app_names": app_names,
            })

    async def _handle_get_thumbnail(self, msg: dict[str, Any]) -> None:
        window_id = msg.get("window_id", 0)
        target_id = msg.get("target_id", "")

        if target_id:
            provider = TargetRegistry.get().get_provider(target_id)
        else:
            provider, _ = self._provider_for_window(window_id)

        jpeg = (await _run_sync(provider.capture_window, window_id, 600, 50)) if provider else None
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

    async def _handle_subscribe_thumbnails(self, msg: dict[str, Any]) -> None:
        """Subscribe to the thumbnail rotation scheduler.

        The client receives a stream of thumbnail updates instead of
        requesting them individually. Much more efficient for many windows.
        """
        from hort.thumbnailer import ThumbnailScheduler

        scheduler = ThumbnailScheduler.get()
        subscribe = msg.get("subscribe", True)
        if subscribe:
            scheduler.subscribe(self)
            # Send all cached thumbnails immediately so the UI isn't blank
            for wid, b64 in scheduler.get_all_cached().items():
                await self.send({"type": "thumbnail", "window_id": wid, "data": b64})
        else:
            scheduler.unsubscribe(self)

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
        workspaces = await _run_sync(provider.get_workspaces)
        current = await _run_sync(provider.get_current_index)
        await self.send({
            "type": "spaces",
            "spaces": [
                {"index": ws.index, "is_current": ws.is_current}
                for ws in workspaces
            ],
            "current": current,
            "count": len(workspaces),
        })

    async def _handle_switch_space(self, msg: dict[str, Any]) -> None:
        provider = self._provider()
        index = msg.get("index", 0)
        ok = (await _run_sync(provider.switch_to, index)) if provider else False
        await self.send({"type": "space_switched", "ok": ok, "target": index})

    async def _handle_stream_config(self, msg: dict[str, Any]) -> None:
        try:
            data = {k: v for k, v in msg.items() if k != "type"}
            target_id = data.pop("target_id", "")
            config = StreamConfig(**data)
            if self._entry is not None:
                self._entry.stream_config = config
                self._entry.active_window_id = config.window_id
                if target_id:
                    self._entry.active_target_id = target_id
                elif self._target_id != "all":
                    self._entry.active_target_id = self._target_id
                else:
                    _, resolved = self._provider_for_window(config.window_id)
                    self._entry.active_target_id = resolved
                # Cache provider + window for input (non-blocking lookup)
                p = self._provider() if self._target_id != "all" else (
                    TargetRegistry.get().get_provider(self._entry.active_target_id)
                )
                self._cached_provider = p
                if p:
                    wins = await _run_sync(p.list_windows)
                    self._cached_window = next(
                        (w for w in wins if w.window_id == config.window_id), None
                    )
            await self.send({"type": "stream_config_ack", "window_id": config.window_id})
        except Exception:
            await self.send({"type": "error", "message": "Invalid stream config"})

    async def _handle_stream_ack(self, msg: dict[str, Any]) -> None:
        from hort.stream import handle_stream_ack
        if self._entry:
            handle_stream_ack(self._entry, msg)

    async def _handle_stream_stop(self, msg: dict[str, Any]) -> None:
        if self._entry:
            self._entry.stream_config = None
            if self._entry.stream_ws is not None:
                try:
                    await self._entry.stream_ws.close(code=4002, reason="stream_stop")
                except Exception:
                    pass

    async def _handle_input(self, msg: dict[str, Any]) -> None:
        try:
            win = self._cached_window
            provider = self._cached_provider
            if win is None or provider is None:
                logger.warning("Input dropped: cached_window=%s cached_provider=%s", win, provider)
                return
            event_data: dict[str, Any] = {
                k: v for k, v in msg.items() if k != "type"
            }
            if "event_type" in event_data:
                event_data["type"] = event_data.pop("event_type")
            event = InputEvent(**event_data)

            # Debug: log coordinate mapping for clicks
            if event.type in ("click", "double_click", "right_click"):
                sx = win.bounds.x + event.nx * win.bounds.width
                sy = win.bounds.y + event.ny * win.bounds.height
                logger.info(
                    "Input: %s nx=%.3f ny=%.3f → screen=(%.0f, %.0f) "
                    "bounds=(%.0f,%.0f,%.0f,%.0f) pid=%d window=%s",
                    event.type, event.nx, event.ny, sx, sy,
                    win.bounds.x, win.bounds.y, win.bounds.width, win.bounds.height,
                    win.owner_pid, win.window_name,
                )

            # Run input in executor — may call docker exec for Linux targets
            await _run_sync(provider.handle_input, event, win.bounds, win.owner_pid)
        except Exception:
            logger.exception("Input error")

    # ----- Terminal management -----

    async def _handle_terminal_spawn(self, msg: dict[str, Any]) -> None:
        from hort.termd_client import ensure_daemon, spawn_terminal

        ensure_daemon()
        target_id = msg.get("target_id", "local-macos")
        cols = msg.get("cols", 120)
        rows = msg.get("rows", 30)
        command = msg.get("command")
        cmd_list = command.split() if isinstance(command, str) else (command or None)
        resp = await spawn_terminal(target_id, command=cmd_list, cols=cols, rows=rows)
        if resp.get("ok"):
            title = msg.get("title") or resp.get("title", "shell")
            await self.send({
                "type": "terminal_spawned",
                "terminal_id": resp["terminal_id"],
                "target_id": resp.get("target_id", target_id),
                "title": title,
            })
        else:
            await self.send({"type": "error", "message": resp.get("error", "Spawn failed")})

    async def _handle_terminal_list(self) -> None:
        from hort.termd_client import ensure_daemon, list_terminals

        terminals: list[dict] = []
        try:
            ensure_daemon()
            terminals = await list_terminals()
        except Exception:
            pass  # termd not available — still show tmux sessions

        # Also include tmux hort_ sessions (shown alongside PTY terminals)
        try:
            from hort.tmux import list_sessions
            from hort.targets import TargetRegistry
            # Use the first registered target so tmux sessions appear
            # in the same grid as regular terminals
            default_target = ""
            try:
                targets = TargetRegistry.get().list_targets()
                if targets:
                    default_target = targets[0].id
            except Exception:
                pass

            from hort.extensions.core.code_watch.provider import _detect_session_state

            for s in list_sessions():
                info = _detect_session_state(s.short_name, s.current_command)
                terminals.append({
                    "terminal_id": f"tmux:{s.short_name}",
                    "target_id": default_target,
                    "title": s.short_name,
                    "cols": 0,
                    "rows": 0,
                    "alive": True,
                    "created_at": 0,
                    "tmux": True,
                    "busy": info.get("state") not in ("idle",),
                    "command": s.current_command,
                    "attached": s.attached,
                    "border_color": info.get("border_color", ""),
                    "mode": info.get("mode", ""),
                    "claude_state": info.get("state", ""),
                    "idle_seconds": info.get("idle_seconds", 0),
                    "needs_input": info.get("needs_input", False),
                    "last_output": info.get("last_output", ""),
                })
        except Exception:
            pass

        await self.send({
            "type": "terminal_list",
            "terminals": terminals,
        })

    async def _handle_terminal_close(self, msg: dict[str, Any]) -> None:
        from hort.termd_client import close_terminal

        terminal_id = msg.get("terminal_id", "")
        ok = await close_terminal(terminal_id)
        await self.send({
            "type": "terminal_closed",
            "terminal_id": terminal_id,
            "ok": ok,
        })

    async def _handle_terminal_resize(self, msg: dict[str, Any]) -> None:
        from hort.termd_client import resize_terminal

        terminal_id = msg.get("terminal_id", "")
        cols = msg.get("cols", 120)
        rows = msg.get("rows", 30)
        await resize_terminal(terminal_id, cols, rows)

    # ----- Token management (host-side) -----

    async def _handle_token_create(self, msg: dict[str, Any]) -> None:
        from hort.access.tokens import TokenStore

        store = TokenStore()
        permanent = msg.get("permanent", False)
        label = msg.get("label", "")
        duration = msg.get("duration_seconds", 300)

        if permanent:
            token = store.create_permanent(label or "Permanent Key")
        else:
            token = store.create_temporary(label or "Temporary", duration)

        await self.send({
            "type": "token_created",
            "token": token,
            "permanent": permanent,
            "label": label,
        })

    async def _handle_token_list(self) -> None:
        from hort.access.tokens import TokenStore

        store = TokenStore()
        await self.send({
            "type": "token_list",
            "tokens": store.list_tokens(),
        })

    async def _handle_token_verify(self, msg: dict[str, Any]) -> None:
        """Verify a token — called by the access server via tunnel."""
        from hort.access.tokens import TokenStore

        store = TokenStore()
        token = msg.get("token", "")
        valid = store.verify(token)
        await self.send({
            "type": "token_verified",
            "valid": valid,
            "req_id": msg.get("req_id", ""),
        })

    async def _handle_token_revoke(self, msg: dict[str, Any]) -> None:
        from hort.access.tokens import TokenStore

        store = TokenStore()
        count = store.revoke_all_temporary()
        await self.send({
            "type": "tokens_revoked",
            "count": count,
        })

    async def _handle_tunnel_status(self) -> None:
        """Report tunnel connection status."""
        # Check if a tunnel client is running
        import os

        tunnel_active = os.path.exists("/tmp/hort-tunnel.active")
        server_url = ""
        if tunnel_active:
            try:
                from pathlib import Path as _Path

                server_url = _Path("/tmp/hort-tunnel.active").read_text().strip()
            except OSError:
                pass
        await self.send({
            "type": "tunnel_status",
            "active": tunnel_active,
            "server_url": server_url,
        })

    # ── Browser camera ──

    async def _handle_camera_offer(self, msg: dict[str, Any]) -> None:
        """Browser offers to share its camera. Creates a BrowserCameraSession."""
        from hort.media import SourceRegistry
        from hort.media_browser_cam import BrowserCameraSession

        device_name = msg.get("device_name", "Browser Camera")
        width = msg.get("width", 1280)
        height = msg.get("height", 720)
        session_id = self.session_id

        source_id = f"cam:browser_{session_id[:8]}"

        # Register as a camera session in the CameraProvider
        cam_provider = SourceRegistry.get().get_provider("camera")
        if cam_provider is None:
            await self.send({"type": "camera_offer_ack", "ok": False, "error": "no camera provider"})
            return

        browser_session = BrowserCameraSession(session_id, device_name, width, height)
        browser_session.start()
        cam_provider._sessions[source_id] = browser_session
        cam_provider._device_map[source_id] = -1  # no physical device

        # Store ref on the controller so stream WS can find it
        self._browser_camera_source_id = source_id

        await self.send({
            "type": "camera_offer_ack",
            "ok": True,
            "source_id": source_id,
        })
        logger.info("Browser camera registered: %s (%s, %dx%d)", source_id, device_name, width, height)

    async def _handle_camera_stop(self, msg: dict[str, Any]) -> None:
        """Browser stops sharing its camera."""
        from hort.media import SourceRegistry

        source_id = getattr(self, "_browser_camera_source_id", "")
        if not source_id:
            return

        cam_provider = SourceRegistry.get().get_provider("camera")
        if cam_provider:
            session = cam_provider._sessions.pop(source_id, None)
            if session:
                session.stop()

        self._browser_camera_source_id = ""
        await self.send({"type": "camera_stopped", "source_id": source_id})
        logger.info("Browser camera stopped: %s", source_id)

