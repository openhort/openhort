"""Core data models for the llming framework.

Every piece of data crossing a llming boundary inherits from one of these:

- ``LlmingData`` — root, carries ``version``
- ``PowerInput`` — power request parameters
- ``PowerOutput`` — power response with HTTP status codes
- ``PulseEvent`` — named channel event payload
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LlmingData(BaseModel):
    """Root for all data crossing llming boundaries.

    The ``version`` field enables forward compatibility. Bump it
    when you make a breaking change to the model. Add new optional
    fields without bumping (they're backward-compatible).
    """

    version: int = Field(default=1, description="Schema version")

    model_config = {"extra": "allow", "populate_by_name": True}


class PowerInput(LlmingData):
    """Base for power input parameters.

    Example::

        class MetricsRequest(PowerInput):
            version: int = 1
            limit: int = 30
            include_history: bool = False
    """

    version: int = 1


class PowerOutput(LlmingData):
    """Base for power responses. HTTP status codes.

    Example::

        class MetricsResponse(PowerOutput):
            version: int = 2
            cpu: float
            memory: float

        return MetricsResponse(cpu=42.0, memory=68.5)      # code=200
        return PowerOutput(code=500, message="Offline")     # error
        return PowerOutput(code=403, message="Admin only")  # forbidden
        return PowerOutput(code=404, message="Not found")   # not found
    """

    version: int = 1
    code: int = Field(default=200, description="HTTP-like status code")
    message: str = Field(default="", description="Human-readable detail")

    @property
    def ok(self) -> bool:
        """True if 200 <= code < 300."""
        return 200 <= self.code < 300


class PulseEvent(LlmingData):
    """Base for named channel event payloads.

    Example::

        class CpuSpike(PulseEvent):
            version: int = 1
            cpu: float
            threshold: float

        await self.emit("cpu_spike", CpuSpike(cpu=95, threshold=90))
    """

    version: int = 1
