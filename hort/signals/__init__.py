"""Signal system — event bus, processors, triggers, and watchers.

Provides push-based event infrastructure complementing MCP's
request/response model.
"""

from hort.signals.bus import SignalBus, get_bus, reset_bus
from hort.signals.engine import LogReactionHandler, ReactionHandler, TriggerEngine
from hort.signals.models import (
    Processor,
    Reaction,
    Signal,
    Trigger,
    TriggerCondition,
    WatcherConfig,
)
from hort.signals.processors import (
    evaluate_condition,
    register_processor,
    render_template,
    run_pipeline,
)
from hort.signals.watchers import PollingWatcher, TimerWatcher, WatcherBase

__all__ = [
    "Signal",
    "Trigger",
    "TriggerCondition",
    "Reaction",
    "Processor",
    "WatcherConfig",
    "SignalBus",
    "get_bus",
    "reset_bus",
    "TriggerEngine",
    "ReactionHandler",
    "LogReactionHandler",
    "register_processor",
    "run_pipeline",
    "evaluate_condition",
    "render_template",
    "WatcherBase",
    "TimerWatcher",
    "PollingWatcher",
]
