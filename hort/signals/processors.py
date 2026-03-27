"""Signal processors — lightweight, stateless pipeline steps.

Each processor is a function ``(Signal, config) -> Signal | None``.
Returning ``None`` drops the signal (pipeline stops).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable

from hort.signals.models import Processor, Signal

logger = logging.getLogger("hort.signals.processors")

ProcessorFn = Callable[[Signal, dict[str, Any]], Signal | None]

_REGISTRY: dict[str, ProcessorFn] = {}


def register_processor(name: str) -> Callable[[ProcessorFn], ProcessorFn]:
    """Decorator to register a named processor type."""
    def decorator(fn: ProcessorFn) -> ProcessorFn:
        _REGISTRY[name] = fn
        return fn
    return decorator


def get_processor(name: str) -> ProcessorFn | None:
    """Look up a processor by name."""
    return _REGISTRY.get(name)


async def run_pipeline(signal: Signal, pipeline: list[Processor]) -> Signal | None:
    """Run a signal through a processor pipeline.

    Returns ``None`` if any step drops the signal.
    """
    current = signal.model_copy(deep=True)
    for step in pipeline:
        fn = get_processor(step.processor_type)
        if fn is None:
            logger.warning("Unknown processor: %s", step.processor_type)
            return None
        result = fn(current, step.config)
        if result is None:
            return None
        current = result
    return current


# ── Condition evaluation (shared by filter processor + trigger engine) ──


def evaluate_condition(value: Any, operator: str, target: Any) -> bool:
    """Evaluate a condition operator."""
    if operator == "eq":
        return value == target
    if operator == "ne":
        return value != target
    if operator == "gt":
        return value is not None and value > target
    if operator == "lt":
        return value is not None and value < target
    if operator == "gte":
        return value is not None and value >= target
    if operator == "lte":
        return value is not None and value <= target
    if operator == "in":
        return value in target if isinstance(target, (list, set, tuple)) else False
    if operator == "contains":
        return target in value if isinstance(value, str) else False
    if operator == "matches":
        return bool(re.search(str(target), str(value))) if value is not None else False
    return False


def render_template(template: str, data: dict[str, Any]) -> str:
    """Simple ``{field}`` template rendering."""
    result = template
    for key, val in data.items():
        result = result.replace(f"{{{key}}}", str(val))
    return result


# ── Built-in processors ────────────────────────────────────────────


@register_processor("filter")
def _filter(signal: Signal, config: dict[str, Any]) -> Signal | None:
    """Drop the signal if the condition is false."""
    field = config.get("field", "")
    value = signal.data.get(field)
    operator = config.get("operator", "eq")
    target = config.get("value")
    if evaluate_condition(value, operator, target):
        return signal
    return None


@register_processor("transform")
def _transform(signal: Signal, config: dict[str, Any]) -> Signal | None:
    """Rename or compute fields."""
    for out_field, expr in config.get("mappings", {}).items():
        if isinstance(expr, str) and expr.startswith("{") and expr.endswith("}"):
            source = expr[1:-1]
            signal.data[out_field] = signal.data.get(source)
        else:
            signal.data[out_field] = expr
    return signal


@register_processor("template")
def _template(signal: Signal, config: dict[str, Any]) -> Signal | None:
    """Render a text template into a new field."""
    tpl = config.get("template", "")
    out = config.get("output_field", "rendered")
    signal.data[out] = render_template(tpl, signal.data)
    return signal


_debounce_state: dict[str, float] = {}


@register_processor("debounce")
def _debounce(signal: Signal, config: dict[str, Any]) -> Signal | None:
    """Suppress duplicate signals within a time window."""
    window = config.get("window_seconds", 10)
    key = f"{signal.signal_type}:{signal.source}"
    now = time.monotonic()
    last = _debounce_state.get(key, 0.0)
    if now - last < window:
        return None
    _debounce_state[key] = now
    return signal


_aggregate_state: dict[str, list[Signal]] = {}


@register_processor("aggregate")
def _aggregate(signal: Signal, config: dict[str, Any]) -> Signal | None:
    """Collect N signals, emit one summary."""
    count = config.get("count", 5)
    fields = config.get("fields", [])
    operation = config.get("operation", "average")
    key = f"{signal.signal_type}:{signal.source}"
    buf = _aggregate_state.setdefault(key, [])
    buf.append(signal)
    if len(buf) < count:
        return None
    result = signal.model_copy(deep=True)
    for field in fields:
        values = [s.data.get(field) for s in buf if field in s.data]
        numeric = [v for v in values if isinstance(v, (int, float))]
        if numeric:
            if operation == "average":
                result.data[field] = sum(numeric) / len(numeric)
            elif operation == "sum":
                result.data[field] = sum(numeric)
            elif operation == "min":
                result.data[field] = min(numeric)
            elif operation == "max":
                result.data[field] = max(numeric)
    _aggregate_state[key] = []
    return result


def reset_processor_state() -> None:
    """Clear stateful processor state (for testing)."""
    _debounce_state.clear()
    _aggregate_state.clear()
