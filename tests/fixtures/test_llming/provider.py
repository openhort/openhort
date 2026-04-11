"""Minimal test llming for subprocess isolation tests."""

from __future__ import annotations

from typing import Any

from hort.llming import Llming, Power, PowerType


class TestLlming(Llming):
    _counter: int = 0

    def activate(self, config: dict[str, Any]) -> None:
        self._counter = config.get("start_count", 0)

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="echo",
                type=PowerType.MCP,
                description="Echo back the input",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            ),
            Power(
                name="count",
                type=PowerType.MCP,
                description="Increment and return counter",
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        if name == "echo":
            return {"content": [{"type": "text", "text": args.get("text", "")}]}
        if name == "count":
            self._counter += 1
            return {"content": [{"type": "text", "text": str(self._counter)}]}
        return {"error": f"Unknown power: {name}"}

    def get_pulse(self) -> dict[str, Any]:
        return {"counter": self._counter, "status": "running"}
