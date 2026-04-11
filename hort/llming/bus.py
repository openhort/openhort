"""Message bus — inter-llming communication without direct imports.

All llming-to-llming calls go through the bus. The bus enforces:
- Instance existence check
- Permission checks (group isolation, wire rules)
- Rate limiting (future)
- Audit logging (future)

A llming calling another llming looks the same whether they're on the
same machine, in a container, or on a remote hort — the bus routes
through H2H if needed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hort.llming.base import Llming

logger = logging.getLogger(__name__)


class MessageBus:
    """Central message bus for inter-llming communication.

    Routes power calls between llming instances. Singleton.
    """

    _instance: MessageBus | None = None

    def __init__(self) -> None:
        # {instance_name: Llming}
        self._instances: dict[str, Llming] = {}

    @classmethod
    def get(cls) -> MessageBus:
        """Get or create the singleton MessageBus."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def register(self, instance_name: str, llming: Llming) -> None:
        """Register a llming instance on the bus."""
        self._instances[instance_name] = llming

    def unregister(self, instance_name: str) -> None:
        """Remove a llming instance from the bus."""
        self._instances.pop(instance_name, None)

    def get_instance(self, name: str) -> Llming | None:
        """Look up a llming instance by name."""
        return self._instances.get(name)

    def list_instances(self) -> list[str]:
        """List all registered instance names."""
        return list(self._instances.keys())

    async def call(
        self,
        source: str,
        target: str,
        power: str,
        args: dict[str, Any],
    ) -> Any:
        """Route a power call from source to target.

        Raises ValueError if the target doesn't exist.
        """
        llming = self._instances.get(target)
        if llming is None:
            raise ValueError(f"Unknown llming instance: {target}")

        # TODO: permission checks (group isolation, wire rules)
        # TODO: rate limiting
        # TODO: audit logging
        # TODO: H2H routing for remote instances

        logger.info("Bus: %s → %s.%s", source, target, power)
        return await llming.execute_power(power, args)

    def power_catalog(self) -> dict[str, list[dict[str, Any]]]:
        """Return all powers from all registered instances.

        Lets any llming discover what others offer::

            catalog = await self.discover("system-monitor")
        """
        from pydantic import BaseModel

        catalog: dict[str, list[dict[str, Any]]] = {}
        for name, instance in self._instances.items():
            catalog[name] = [
                {
                    "name": p.name,
                    "type": p.type.value,
                    "description": p.description,
                    "input_schema": (
                        p.input_schema.model_json_schema()
                        if isinstance(p.input_schema, type) and issubclass(p.input_schema, BaseModel)
                        else p.input_schema
                    ),
                    "output_schema": (
                        p.output_schema.model_json_schema()
                        if isinstance(p.output_schema, type) and issubclass(p.output_schema, BaseModel)
                        else p.output_schema
                    ),
                }
                for p in instance.get_powers()
            ]
        return catalog
