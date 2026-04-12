"""Decorators for llming powers and pulse subscriptions.

Powers::

    @power("get_status", description="Get current status")
    async def get_status(self) -> StatusResponse:
        return StatusResponse(cpu=42.0)

    @power("hort", sub="info", description="Container status", command=True)
    async def hort_info(self) -> str:
        return "..."

    @power("hort", sub="restart", description="Restart", command=True, admin_only=True)
    async def hort_restart(self) -> str:
        return "Restarted."

    @power("cpu", description="CPU usage", command=True)
    async def cpu_command(self) -> str:
        return f"CPU: {self._cpu}%"

Pulse subscriptions::

    @on("cpu_spike")
    async def handle_spike(self, data: dict) -> None: ...

    @on("tick:1hz")
    async def every_second(self, data: dict) -> None: ...

Dependency waiting::

    @on_ready("system-monitor", "hue-bridge")
    async def deps_loaded(self) -> None: ...
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Type, get_type_hints

from pydantic import BaseModel


@dataclass(frozen=True)
class PowerMeta:
    """Metadata attached to a @power-decorated method."""

    name: str
    sub: str          # subcommand (e.g. "info" for /hort info). Empty = no sub.
    short: str        # first line of docstring (for /help, MCP tool list)
    long: str         # rest of docstring (for detailed help, API docs)
    mcp: bool         # expose as MCP tool
    command: bool     # expose as slash command (listed in /help)
    admin_only: bool

    @property
    def description(self) -> str:
        """Full description (short + long)."""
        if self.long:
            return f"{self.short}\n\n{self.long}"
        return self.short
    input_model: Type[BaseModel] | None
    output_model: Type[BaseModel] | None

    @property
    def full_name(self) -> str:
        """Full power name including subcommand: "hort.info" or "cpu"."""
        if self.sub:
            return f"{self.name}.{self.sub}"
        return self.name

    @property
    def command_name(self) -> str:
        """Slash command display: "/hort info" or "/cpu"."""
        if self.sub:
            return f"/{self.name} {self.sub}"
        return f"/{self.name}"


def power(
    name: str,
    *,
    sub: str = "",
    mcp: bool = True,
    command: bool = False,
    admin_only: bool = False,
) -> Callable:
    """Mark a method as a power handler.

    Description comes from the docstring:
    - First line = short description (shown in /help, MCP tool list)
    - Rest (after blank line) = long description (detailed help, API docs)

    Args:
        name: Power name (e.g. "get_metrics", "hort").
        sub: Subcommand (e.g. "info" for /hort info).
        mcp: Expose as MCP tool (default True).
        command: Expose as slash command in /help (default False).
        admin_only: Restrict to admin users.
    """

    def decorator(fn: Callable) -> Callable:
        hints = _safe_get_hints(fn)
        params = list(inspect.signature(fn).parameters.values())

        input_model = None
        non_self = [p for p in params if p.name != "self"]
        if non_self:
            hint = hints.get(non_self[0].name)
            if hint and isinstance(hint, type) and issubclass(hint, BaseModel):
                input_model = hint

        output_model = None
        ret = hints.get("return")
        if ret and isinstance(ret, type) and issubclass(ret, BaseModel):
            output_model = ret

        short, long = _parse_docstring(fn.__doc__)

        fn._power_meta = PowerMeta(  # type: ignore[attr-defined]
            name=name,
            sub=sub,
            short=short,
            long=long,
            mcp=mcp,
            command=command,
            admin_only=admin_only,
            input_model=input_model,
            output_model=output_model,
        )
        return fn

    return decorator


def _parse_docstring(doc: str | None) -> tuple[str, str]:
    """Extract short and long description from a docstring.

    First line = short. Everything after the first blank line = long.
    """
    if not doc:
        return ("", "")
    lines = doc.strip().splitlines()
    short = lines[0].strip()
    long = ""
    if len(lines) > 2:
        # Find first blank line, take everything after
        for i, line in enumerate(lines[1:], 1):
            if not line.strip():
                long = "\n".join(l.strip() for l in lines[i + 1:]).strip()
                break
    return (short, long)


def collect_powers(instance: object) -> dict[str, tuple[Callable, PowerMeta]]:
    """Collect all @power-decorated methods from an instance.

    Returns {full_name: (bound_method, PowerMeta)}.
    Full name is "name.sub" for subcommands, "name" for root powers.
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
        handlers[meta.full_name] = (bound, meta)
    return handlers


async def invoke_handler(handler: Callable, meta: PowerMeta, args: dict[str, Any]) -> Any:
    """Invoke a power handler with input parsing and async wrapping.

    Supports:
    - Pydantic model input (from dict or positional string)
    - No-input handlers (just self)
    - Dict kwargs
    - Sync handlers wrapped in asyncio.to_thread()
    """
    is_async = asyncio.iscoroutinefunction(handler)

    if meta.input_model is not None:
        # Positional args: {"args": "val1 val2"} → map to fields in order
        if list(args.keys()) == ["args"] and isinstance(args.get("args"), str):
            parsed = _parse_positional(meta.input_model, args["args"])
        else:
            parsed = meta.input_model(**args)
        if is_async:
            return await handler(parsed)
        return await asyncio.to_thread(handler, parsed)

    sig = inspect.signature(handler)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    if not params:
        if is_async:
            return await handler()
        return await asyncio.to_thread(handler)

    if is_async:
        return await handler(**args)
    return await asyncio.to_thread(handler, **args)


def _parse_positional(model: type[BaseModel], args_str: str) -> BaseModel:
    """Parse positional args string into a Pydantic model.

    Maps space-separated values to model fields in declaration order.
    Skips 'version' field. Pydantic handles type coercion.

    Example:
        class LightControl(PowerInput):
            light_id: str
            brightness: int = 255

        _parse_positional(LightControl, "1 200")
        → LightControl(light_id="1", brightness=200)
    """
    parts = args_str.split() if args_str.strip() else []
    fields = [f for f in model.model_fields.keys() if f != "version"]

    kwargs: dict[str, Any] = {}
    for i, field_name in enumerate(fields):
        if i < len(parts):
            kwargs[field_name] = parts[i]

    return model(**kwargs)


def _safe_get_hints(fn: Callable) -> dict[str, Any]:
    try:
        return get_type_hints(fn)
    except Exception:
        return {}


# ── @on decorator — pulse channel subscriptions ──


@dataclass(frozen=True)
class OnMeta:
    channel: str


def on(channel: str) -> Callable:
    """Subscribe a method to a named pulse channel.

    Built-in: tick:30hz, tick:10hz, tick:1hz, tick:slow
    Lifecycle: llming:started, llming:stopped
    Custom: cpu_spike, disk_usage, etc.
    """
    def decorator(fn: Callable) -> Callable:
        if not hasattr(fn, "_on_meta"):
            fn._on_meta = []  # type: ignore[attr-defined]
        fn._on_meta.append(OnMeta(channel=channel))  # type: ignore[attr-defined]
        return fn
    return decorator


def collect_subscriptions(instance: object) -> list[tuple[str, Callable]]:
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


# ── @on_ready decorator ──


@dataclass(frozen=True)
class OnReadyMeta:
    dependencies: tuple[str, ...]


def on_ready(*llming_names: str) -> Callable:
    """Call a method once when all listed llmings have started."""
    def decorator(fn: Callable) -> Callable:
        fn._on_ready_meta = OnReadyMeta(dependencies=llming_names)  # type: ignore[attr-defined]
        return fn
    return decorator


def collect_ready_handlers(instance: object) -> list[tuple[tuple[str, ...], Callable]]:
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
