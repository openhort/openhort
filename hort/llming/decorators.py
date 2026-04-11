"""Decorators for declaring llming powers and pulse schemas.

Usage::

    from hort.llming.decorators import power
    from hort.llming.models import PowerInput, PowerOutput

    class MyLlming(Llming):
        @power("get_status", description="Get current status")
        async def get_status(self) -> StatusResponse:
            return StatusResponse(cpu=42.0)

        @power("reboot", description="Reboot the system", mcp=False)
        async def reboot(self) -> PowerOutput:
            ...

        @power("cpu", description="Show CPU usage", command="/cpu")
        async def cpu_command(self) -> str:
            return f"CPU: {self._cpu}%"

Every ``@power`` is exposed as an MCP tool by default. Set ``mcp=False``
to hide from AI agents (e.g. internal session management). Set
``command="/name"`` to also register as a slash command for connectors.
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
