"""Dice Roller — hybrid llming with @power commands and live card."""

from __future__ import annotations

import random
import time
from typing import Any

from pydantic import Field

from hort.llming import Llming, power, PowerInput, PowerOutput, PulseEvent


class RollRequest(PowerInput):
    """Dice roll parameters."""
    version: int = 1
    sides: int = Field(default=6, description="Number of sides", ge=2, le=100)
    count: int = Field(default=1, description="Number of dice", ge=1, le=20)


class RollResult(PowerOutput):
    """Dice roll result."""
    version: int = 1
    rolls: list[int] = []
    total: int = 0
    sides: int = 6


class DiceRollEvent(PulseEvent):
    """Emitted on every roll."""
    version: int = 1
    rolls: list[int] = []
    total: int = 0
    sides: int = 6


class DiceRoller(Llming):
    """Roll dice via command or MCP tool. History stored in vault."""

    def activate(self, config: dict[str, Any]) -> None:
        self.log.info("Dice roller activated")

    @power("roll", command=True)
    async def roll(self, req: RollRequest) -> RollResult:
        """Roll dice. Usage: /roll [sides] [count]"""
        rolls = [random.randint(1, req.sides) for _ in range(req.count)]
        total = sum(rolls)

        # Store in vault
        history = self.vault.get("history", default={"rolls": []})
        history_list = history.get("rolls", [])
        history_list.append({"rolls": rolls, "total": total, "sides": req.sides, "ts": time.time()})
        if len(history_list) > 50:
            history_list = history_list[-50:]
        self.vault.set("history", {"rolls": history_list})
        self.vault.set("state", {"last_roll": rolls, "last_total": total, "sides": req.sides})

        # Emit pulse
        await self.emit("dice_roll", DiceRollEvent(rolls=rolls, total=total, sides=req.sides))

        return RollResult(rolls=rolls, total=total, sides=req.sides)

    @power("roll_history", command=True)
    async def roll_history(self) -> str:
        """Show recent dice roll history."""
        history = self.vault.get("history", default={"rolls": []})
        rolls = history.get("rolls", [])
        if not rolls:
            return "No rolls yet. Try /roll"
        lines = ["Recent rolls:"]
        for r in rolls[-10:]:
            dice = ", ".join(str(d) for d in r["rolls"])
            lines.append(f"  d{r['sides']}: [{dice}] = {r['total']}")
        return "\n".join(lines)
