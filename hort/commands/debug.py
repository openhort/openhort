"""WS commands for debug/introspection — console, JS execution, llming routing."""

from __future__ import annotations

from typing import Any

from llming_com import WSRouter

from hort.commands._registry import get_llming_registry

router = WSRouter(prefix="debug")


@router.handler("console")
async def debug_console(controller: Any, level: str = "", pattern: str = "", since: int = 0) -> dict[str, Any]:
    """Read browser console logs."""
    return await controller.get_console_logs(level=level, pattern=pattern, since=since)


@router.handler("eval")
async def debug_eval(controller: Any, code: str = "") -> dict[str, Any]:
    """Execute JS in the browser and return the result."""
    if not code:
        return {"error": "no code"}
    return await controller.eval_js(code)


@router.handler("run_js")
async def debug_run_js(controller: Any, code: str = "") -> dict[str, Any]:
    """Execute JS in the browser (fire-and-forget)."""
    if not code:
        return {"error": "no code"}
    await controller.run_js(code)
    return {"ok": True}


@router.handler("call")
async def debug_call(controller: Any, llming: str = "", power: str = "", args: dict | None = None) -> dict[str, Any]:
    """Route a power call to a specific llming. Returns the result."""
    from hort.llming.base import Llming

    registry = get_llming_registry()
    if not registry:
        return {"error": "no registry"}

    inst = registry.get_instance(llming)
    if inst is None:
        return {"error": f"llming '{llming}' not found"}
    if not isinstance(inst, Llming):
        return {"error": f"'{llming}' is not a Llming instance"}

    result = await inst.execute_power(power, args or {})

    # Normalize result for JSON transport
    if isinstance(result, str):
        return {"result": result}
    if isinstance(result, dict):
        return {"result": result}
    return {"result": str(result)}
