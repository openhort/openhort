"""ScreenWatcher plugin — monitors windows for changes, emits signals.

Each WatchRule independently polls matching windows, detects visual
changes via frame hashing, and emits signals:

- ``screen.changed`` — the watched window's content changed
- ``screen.idle`` — no change detected for ``idle_threshold`` seconds

Supports app/window name filtering and region selection (full, left,
right, top, bottom, quadrants, center, or custom fractions).
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from typing import Any

from hort.extensions.core.screen_watcher.capture import (
    crop_region,
    frame_hash,
    frames_differ,
)
from hort.extensions.core.screen_watcher.models import (
    ScreenWatcherConfig,
    WatchRule,
)

logger = logging.getLogger("hort.screen_watcher")


class _RuleState:
    """Runtime state for a single watch rule."""

    __slots__ = (
        "rule", "last_hash", "last_change_time", "idle_emitted",
        "task", "matched_window_id", "matched_window_name",
    )

    def __init__(self, rule: WatchRule) -> None:
        self.rule = rule
        self.last_hash: str | None = None
        self.last_change_time: float = time.monotonic()
        self.idle_emitted: bool = False
        self.task: asyncio.Task[None] | None = None
        self.matched_window_id: int | None = None
        self.matched_window_name: str = ""


class ScreenWatcher:
    """Screen watcher — monitors windows for visual changes.

    This is a standalone class (not a PluginBase subclass) so it can be
    tested independently. The plugin integration layer wraps it.
    """

    def __init__(
        self,
        config: ScreenWatcherConfig,
        capture_fn: Any = None,
        list_windows_fn: Any = None,
        emit_signal_fn: Any = None,
        hort_id: str = "local",
    ) -> None:
        self._config = config
        self._capture_fn = capture_fn      # (window_id, max_width, quality) -> bytes|None
        self._list_windows_fn = list_windows_fn  # (app_filter) -> list[WindowInfo]
        self._emit_signal_fn = emit_signal_fn    # async (signal) -> None
        self._hort_id = hort_id
        self._states: list[_RuleState] = []

    async def start(self) -> None:
        """Start watching all enabled rules."""
        for rule in self._config.rules:
            if not rule.enabled:
                continue
            state = _RuleState(rule)
            state.task = asyncio.create_task(self._poll_loop(state))
            self._states.append(state)
        logger.info("ScreenWatcher started with %d rules", len(self._states))

    async def stop(self) -> None:
        """Stop all polling loops."""
        for state in self._states:
            if state.task:
                state.task.cancel()
        self._states.clear()
        logger.info("ScreenWatcher stopped")

    def get_status(self) -> list[dict[str, Any]]:
        """Return status of all watch rules."""
        result = []
        for s in self._states:
            elapsed = time.monotonic() - s.last_change_time
            result.append({
                "name": s.rule.name,
                "window": s.matched_window_name,
                "window_id": s.matched_window_id,
                "idle_seconds": round(elapsed, 1),
                "idle_emitted": s.idle_emitted,
                "last_hash": s.last_hash[:12] if s.last_hash else None,
            })
        return result

    async def _poll_loop(self, state: _RuleState) -> None:
        """Polling loop for a single rule."""
        rule = state.rule
        try:
            while True:
                await asyncio.sleep(rule.poll_interval)
                try:
                    await self._poll_once(state)
                except Exception:
                    logger.exception("Poll error for rule %s", rule.name)
        except asyncio.CancelledError:
            pass

    async def _poll_once(self, state: _RuleState) -> None:
        """Single poll iteration: find window, capture, detect change."""
        rule = state.rule
        loop = asyncio.get_running_loop()

        # Find matching window
        windows = await loop.run_in_executor(
            None, self._list_windows_fn, rule.app_filter,
        )

        matched = None
        for w in windows:
            if rule.window_filter:
                if not fnmatch.fnmatch(
                    w.window_name.lower(), f"*{rule.window_filter.lower()}*",
                ):
                    continue
            matched = w
            break

        if matched is None:
            return  # no matching window found

        state.matched_window_id = matched.window_id
        state.matched_window_name = (
            f"{matched.owner_name}: {matched.window_name}"
        )

        # Capture
        jpeg = await loop.run_in_executor(
            None, self._capture_fn, matched.window_id, rule.max_width, rule.quality,
        )
        if jpeg is None:
            return

        # Crop region
        cropped = await loop.run_in_executor(
            None, crop_region, jpeg, rule.region,
        )

        # Change detection
        current_hash = frame_hash(cropped)
        changed = frames_differ(state.last_hash, current_hash)

        if changed:
            state.last_hash = current_hash
            state.last_change_time = time.monotonic()
            state.idle_emitted = False

            if self._emit_signal_fn:
                from hort.signals.models import Signal

                await self._emit_signal_fn(Signal(
                    signal_type="screen.changed",
                    source=f"screen-watcher/{rule.name}",
                    hort_id=self._hort_id,
                    data={
                        "rule": rule.name,
                        "window": state.matched_window_name,
                        "window_id": matched.window_id,
                        "app": matched.owner_name,
                        "region": rule.region.preset or "custom",
                        "frame_hash": current_hash[:12],
                    },
                ))
        else:
            # Check for idle
            elapsed = time.monotonic() - state.last_change_time
            if elapsed >= rule.idle_threshold and not state.idle_emitted:
                state.idle_emitted = True

                if self._emit_signal_fn:
                    from hort.signals.models import Signal

                    await self._emit_signal_fn(Signal(
                        signal_type="screen.idle",
                        source=f"screen-watcher/{rule.name}",
                        hort_id=self._hort_id,
                        data={
                            "rule": rule.name,
                            "window": state.matched_window_name,
                            "window_id": matched.window_id,
                            "app": matched.owner_name,
                            "idle_seconds": round(elapsed, 1),
                            "last_hash": current_hash[:12],
                        },
                    ))
