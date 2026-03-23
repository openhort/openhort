"""Plugin scheduler — runs interval jobs in executor threads.

Each plugin gets its own ``PluginScheduler`` instance via the context.
Jobs are defined via ``ScheduledMixin.get_jobs()`` or declaratively in
the manifest's ``jobs`` array.

**Critical:** Every job function is wrapped in ``loop.run_in_executor()``
to never block the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobSpec:
    """Definition of a scheduled background job."""

    id: str
    fn_name: str  # method name on the plugin instance
    interval_seconds: float
    run_on_activate: bool = False
    enabled_feature: str = ""  # only run when this feature toggle is on


class PluginScheduler:
    """Manages asyncio tasks for one plugin's interval jobs.

    All job functions run in the default executor (thread pool)
    to avoid blocking the event loop.
    """

    def __init__(self, plugin_id: str) -> None:
        self._plugin_id = plugin_id
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._log = logging.getLogger(f"hort.plugin.{plugin_id}.scheduler")

    def start_job(self, spec: JobSpec, fn: Callable[[], Any]) -> None:
        """Start a job that calls ``fn`` every ``spec.interval_seconds``."""
        if spec.id in self._tasks:
            self.stop_job(spec.id)

        async def _loop() -> None:
            loop = asyncio.get_event_loop()
            if spec.run_on_activate:
                try:
                    await loop.run_in_executor(None, fn)
                except Exception as e:
                    self._log.error("Job %s initial run failed: %s", spec.id, e)
            while True:
                await asyncio.sleep(spec.interval_seconds)
                try:
                    await loop.run_in_executor(None, fn)
                except Exception as e:
                    self._log.error("Job %s failed: %s", spec.id, e)

        task = asyncio.create_task(_loop())
        self._tasks[spec.id] = task
        self._log.info("Started job %s (every %.0fs)", spec.id, spec.interval_seconds)

    def stop_job(self, job_id: str) -> None:
        """Stop a running job by ID."""
        task = self._tasks.pop(job_id, None)
        if task is not None:
            task.cancel()
            self._log.info("Stopped job %s", job_id)

    def stop_all(self) -> None:
        """Stop all running jobs."""
        for job_id in list(self._tasks):
            self.stop_job(job_id)

    @property
    def running_jobs(self) -> list[str]:
        """List of currently running job IDs."""
        return [jid for jid, t in self._tasks.items() if not t.done()]


class ScheduledMixin:
    """Mixin for plugins that need background interval jobs.

    Override ``get_jobs()`` to return job definitions.
    The registry calls this after ``activate()`` and starts each job.

    Example::

        class MyPlugin(PluginBase, ScheduledMixin):
            def get_jobs(self) -> list[JobSpec]:
                return [
                    JobSpec(id="poll", fn_name="poll_data", interval_seconds=30),
                ]

            def poll_data(self) -> None:
                # Runs every 30s in an executor thread
                ...
    """

    def get_jobs(self) -> list[JobSpec]:
        """Return job definitions. Called once after activate."""
        return []
