"""Decorators for llming powers and pulse subscriptions.

Powers::

    @power("get_status", description="Get current status")
    async def get_status(self) -> StatusResponse:
        return StatusResponse(cpu=42.0)

Pulse subscriptions::

    @on("cpu_spike")
    async def handle_spike(self, data: dict) -> None:
        self.log.warning("CPU: %s%%", data["cpu"])

    @on("tick:1hz")
    async def every_second(self, data: dict) -> None:
        self.poll_metrics()

Dependency waiting::

    @on_ready("system-monitor", "hue-bridge")
    async def deps_loaded(self) -> None:
        self.log.info("All dependencies ready")
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Type, get_type_hints

from pydantic import BaseModel


@dataclass(frozen=True)
class PowerMeta:
    """Metadata attached to a @power-decorated method."""

    name: str
    description: str
    mcp: bool
    command: str  # empty = not a slash command
    admin_only: bool
    input_model: Type[BaseModel] | None
    output_model: Type[BaseModel] | None


def power(
    name: str,
    *,
    description: str = "",
    mcp: bool = True,
    command: str = "",
    admin_only: bool = False,
) -> Callable:
    """Mark a method as a power handler.

    Args:
        name: Power name (used in execute_power, MCP tool name, etc.)
        description: Human-readable description. Falls back to docstring.
        mcp: Expose as MCP tool (default True).
        command: Slash command alias (e.g. "/cpu"). Empty = no command.
        admin_only: Restrict to admin users.

    Input/output models are inferred from type hints. If the first
    parameter (after self) is a Pydantic BaseModel subclass, it becomes
    the input schema. If the return type is a BaseModel subclass, it
    becomes the output schema.

    Sync handlers are auto-wrapped in asyncio.to_thread().
    No-parameter handlers (just self) are valid — args are ignored.
    """

    def decorator(fn: Callable) -> Callable:
        hints = _safe_get_hints(fn)
        params = list(inspect.signature(fn).parameters.values())

        # Infer input model from first non-self parameter
        input_model = None
        non_self = [p for p in params if p.name != "self"]
        if non_self:
            hint = hints.get(non_self[0].name)
            if hint and isinstance(hint, type) and issubclass(hint, BaseModel):
                input_model = hint

        # Infer output model from return hint
        output_model = None
        ret = hints.get("return")
        if ret and isinstance(ret, type) and issubclass(ret, BaseModel):
            output_model = ret

        fn._power_meta = PowerMeta(  # type: ignore[attr-defined]
            name=name,
            description=description or fn.__doc__ or "",
            mcp=mcp,
            command=command,
            admin_only=admin_only,
            input_model=input_model,
            output_model=output_model,
        )
        return fn

    return decorator


def collect_powers(instance: object) -> dict[str, tuple[Callable, PowerMeta]]:
    """Collect all @power-decorated methods from an instance.

    Returns {power_name: (bound_method, PowerMeta)}.
    Called once at registration time, not on every request.
    """
    handlers: dict[str, tuple[Callable, PowerMeta]] = {}
    for attr_name in dir(type(instance)):
        try:
            attr = getattr(type(instance), attr_name)
        except Exception:
            continue
        meta = getattr(attr, "_power_meta", None)
        if meta is None:
            continue
        bound = getattr(instance, attr_name)
        handlers[meta.name] = (bound, meta)
    return handlers


async def invoke_handler(handler: Callable, meta: PowerMeta, args: dict[str, Any]) -> Any:
    """Invoke a power handler with proper input parsing and async wrapping.

    - Pydantic input model: parsed from args dict
    - No parameters: called with no args
    - Dict args: passed as kwargs
    - Sync handlers: wrapped in asyncio.to_thread()
    """
    is_async = asyncio.iscoroutinefunction(handler)

    # Pydantic model input — parse and pass as single arg
    if meta.input_model is not None:
        parsed = meta.input_model(**args)
        if is_async:
            return await handler(parsed)
        return await asyncio.to_thread(handler, parsed)

    # No-input handler (just self)
    sig = inspect.signature(handler)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    if not params:
        if is_async:
            return await handler()
        return await asyncio.to_thread(handler)

    # Dict kwargs
    if is_async:
        return await handler(**args)
    return await asyncio.to_thread(handler, **args)


def _safe_get_hints(fn: Callable) -> dict[str, Any]:
    """Get type hints without raising on forward refs."""
    try:
        return get_type_hints(fn)
    except Exception:
        return {}


# ── @on decorator — pulse channel subscriptions ──


@dataclass(frozen=True)
class OnMeta:
    """Metadata attached to an @on-decorated method."""
    channel: str


def on(channel: str) -> Callable:
    """Subscribe a method to a named pulse channel.

    The method is called whenever an event is emitted on this channel.
    Framework wires subscriptions at activation time.

    Built-in channels:
        tick:30hz, tick:10hz, tick:1hz, tick:slow

    Custom channels:
        cpu_spike, memory_warning, llming:started, llming:stopped

    Example::

        @on("cpu_spike")
        async def handle_spike(self, data: dict) -> None:
            self.log.warning("CPU: %s%%", data["cpu"])

        @on("tick:1hz")
        async def poll_metrics(self, data: dict) -> None:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        if not hasattr(fn, "_on_meta"):
            fn._on_meta = []  # type: ignore[attr-defined]
        fn._on_meta.append(OnMeta(channel=channel))  # type: ignore[attr-defined]
        return fn
    return decorator


def collect_subscriptions(instance: object) -> list[tuple[str, Callable]]:
    """Collect all @on-decorated methods from an instance.

    Returns [(channel_name, bound_method), ...].
    """
    subs: list[tuple[str, Callable]] = []
    for attr_name in dir(type(instance)):
        try:
            attr = getattr(type(instance), attr_name)
        except Exception:
            continue
        metas = getattr(attr, "_on_meta", None)
        if not metas:
            continue
        bound = getattr(instance, attr_name)
        for meta in metas:
            subs.append((meta.channel, bound))
    return subs


# ── @on_ready decorator — dependency waiting ──


@dataclass(frozen=True)
class OnReadyMeta:
    """Metadata attached to an @on_ready-decorated method."""
    dependencies: tuple[str, ...]


def on_ready(*llming_names: str) -> Callable:
    """Call a method once when all listed llmings have started.

    Example::

        @on_ready("system-monitor", "hue-bridge")
        async def deps_loaded(self) -> None:
            self.log.info("All dependencies ready")
    """
    def decorator(fn: Callable) -> Callable:
        fn._on_ready_meta = OnReadyMeta(dependencies=llming_names)  # type: ignore[attr-defined]
        return fn
    return decorator


def collect_ready_handlers(instance: object) -> list[tuple[tuple[str, ...], Callable]]:
    """Collect all @on_ready-decorated methods.

    Returns [(("dep1", "dep2"), bound_method), ...].
    """
    handlers: list[tuple[tuple[str, ...], Callable]] = []
    for attr_name in dir(type(instance)):
        try:
            attr = getattr(type(instance), attr_name)
        except Exception:
            continue
        meta = getattr(attr, "_on_ready_meta", None)
        if meta is None:
            continue
        bound = getattr(instance, attr_name)
        handlers.append((meta.dependencies, bound))
    return handlers
