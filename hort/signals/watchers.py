"""Watchers — bridge external event sources into the signal bus."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable

from hort.signals.bus import SignalBus
from hort.signals.models import Signal

logger = logging.getLogger("hort.signals.watchers")

_SENTINEL = object()


class WatcherBase(ABC):
    """Abstract base for event source watchers."""

    @abstractmethod
    async def start(self, bus: SignalBus, hort_id: str) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @property
    @abstractmethod
    def watcher_type(self) -> str: ...


class TimerWatcher(WatcherBase):
    """Emits signals on interval schedules.

    Config::

        schedules:
          - timer_id: daily-check
            interval_seconds: 3600
            signal_type: timer.fired
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._tasks: list[asyncio.Task[None]] = []
        self._bus: SignalBus | None = None
        self._hort_id: str = ""

    @property
    def watcher_type(self) -> str:
        return "timer"

    async def start(self, bus: SignalBus, hort_id: str) -> None:
        self._bus = bus
        self._hort_id = hort_id
        for sched in self._config.get("schedules", []):
            self._tasks.append(asyncio.create_task(self._loop(sched)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def _loop(self, schedule: dict[str, Any]) -> None:
        timer_id = schedule.get("timer_id", "unnamed")
        signal_type = schedule.get("signal_type", "timer.fired")
        interval = schedule.get("interval_seconds", 60)
        try:
            while True:
                await asyncio.sleep(interval)
                if self._bus:
                    await self._bus.emit(Signal(
                        signal_type=signal_type,
                        source=f"timer/{timer_id}",
                        hort_id=self._hort_id,
                        data={
                            "timer_id": timer_id,
                            "scheduled_at": datetime.now(timezone.utc).isoformat(),
                        },
                    ))
        except asyncio.CancelledError:
            pass


class PollingWatcher(WatcherBase):
    """Polls a callable and emits a signal when the return value changes."""

    def __init__(
        self,
        config: dict[str, Any],
        poll_fn: Callable[[], Any],
    ) -> None:
        self._config = config
        self._poll_fn = poll_fn
        self._task: asyncio.Task[None] | None = None
        self._last_value: Any = _SENTINEL
        self._bus: SignalBus | None = None
        self._hort_id: str = ""

    @property
    def watcher_type(self) -> str:
        return "polling"

    async def start(self, bus: SignalBus, hort_id: str) -> None:
        self._bus = bus
        self._hort_id = hort_id
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        interval = self._config.get("interval_seconds", 30)
        signal_type = self._config.get("signal_type", "resource.changed")
        source = self._config.get("source", "polling/unknown")
        try:
            while True:
                await asyncio.sleep(interval)
                loop = asyncio.get_running_loop()
                value = await loop.run_in_executor(None, self._poll_fn)
                if value != self._last_value:
                    self._last_value = value
                    if self._bus:
                        await self._bus.emit(Signal(
                            signal_type=signal_type,
                            source=source,
                            hort_id=self._hort_id,
                            data={"value": value},
                        ))
        except asyncio.CancelledError:
            pass
