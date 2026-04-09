"""Tests for the LlmingBase v2 framework — base class, powers, pulse, bus, registry."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from hort.llming import LlmingBase, MessageBus, Power, PowerType, PulseBus
from hort.llming.registry import LlmingClass, LlmingRegistry
from hort.ext.manifest import ExtensionManifest


# ── Test models ──


class MetricsRequest(BaseModel):
    include_per_core: bool = False


class MetricsResponse(BaseModel):
    cpu: float = 0.0
    memory: float = 0.0
    per_core: list[float] = []


# ── Test llmings ──


class FakeMonitor(LlmingBase):
    """Test llming with all three power types."""

    _latest: dict[str, Any] = {}

    def activate(self, config: dict[str, Any]) -> None:
        self._latest = {"cpu": 42.0, "memory": 65.0}

    def get_powers(self) -> list[Power]:
        return [
            Power(
                name="get_metrics",
                type=PowerType.ACTION,
                description="Get system metrics",
                input_schema=MetricsRequest,
                output_schema=MetricsResponse,
            ),
            Power(
                name="cpu",
                type=PowerType.COMMAND,
                description="Show CPU usage",
                admin_only=True,
            ),
            Power(
                name="get_cpu_raw",
                type=PowerType.MCP,
                description="Get raw CPU data",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    async def execute_power(self, name: str, args: dict[str, Any]) -> Any:
        if name == "get_metrics":
            return MetricsResponse(
                cpu=self._latest.get("cpu", 0),
                memory=self._latest.get("memory", 0),
                per_core=[10.0, 20.0] if args.get("include_per_core") else [],
            )
        if name == "cpu":
            return f"CPU: {self._latest.get('cpu', '?')}%"
        if name == "get_cpu_raw":
            return {"cpu_percent": self._latest.get("cpu", 0)}
        return {"error": f"Unknown power: {name}"}

    def get_pulse(self) -> dict[str, Any]:
        return self._latest

    def get_pulse_channels(self) -> list[str]:
        return ["cpu_spike", "memory_warning"]


class FakeDashboard(LlmingBase):
    """Test llming that consumes other llmings via the bus."""

    received_events: list[dict[str, Any]] = []

    def activate(self, config: dict[str, Any]) -> None:
        self.received_events = []

    async def on_spike(self, data: dict[str, Any]) -> None:
        self.received_events.append(data)


# ── Fixtures ──


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset all singletons before each test."""
    PulseBus.reset()
    MessageBus.reset()
    LlmingRegistry.reset()
    yield
    PulseBus.reset()
    MessageBus.reset()
    LlmingRegistry.reset()


# ── Power tests ──


class TestPower:
    def test_mcp_power_to_tool_def(self) -> None:
        p = Power(name="test", type=PowerType.MCP, description="A test tool")
        tool = p.to_mcp_tool_def()
        assert tool["name"] == "test"
        assert tool["description"] == "A test tool"
        assert tool["inputSchema"] == {"type": "object", "properties": {}}

    def test_action_power_pydantic_schema(self) -> None:
        p = Power(
            name="get_metrics",
            type=PowerType.ACTION,
            description="Metrics",
            input_schema=MetricsRequest,
            output_schema=MetricsResponse,
        )
        tool = p.to_mcp_tool_def()
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "include_per_core" in schema["properties"]

    def test_command_power_to_connector_command(self) -> None:
        p = Power(
            name="status",
            type=PowerType.COMMAND,
            description="Show status",
            admin_only=True,
        )
        cmd = p.to_connector_command()
        assert cmd["command"] == "status"
        assert cmd["admin_only"] is True


# ── LlmingBase tests ──


class TestLlmingBase:
    def test_lifecycle(self) -> None:
        mon = FakeMonitor()
        mon._instance_name = "test-mon"
        mon._class_name = "fake-monitor"
        mon.activate({"threshold": 90})
        assert mon.get_pulse() == {"cpu": 42.0, "memory": 65.0}
        mon.deactivate()

    def test_get_powers(self) -> None:
        mon = FakeMonitor()
        powers = mon.get_powers()
        assert len(powers) == 3
        types = {p.type for p in powers}
        assert types == {PowerType.MCP, PowerType.COMMAND, PowerType.ACTION}

    @pytest.mark.asyncio
    async def test_execute_power(self) -> None:
        mon = FakeMonitor()
        mon.activate({})
        result = await mon.execute_power("cpu", {})
        assert result == "CPU: 42.0%"

    @pytest.mark.asyncio
    async def test_execute_action_power(self) -> None:
        mon = FakeMonitor()
        mon.activate({})
        result = await mon.execute_power("get_metrics", {"include_per_core": True})
        assert isinstance(result, MetricsResponse)
        assert result.cpu == 42.0
        assert result.per_core == [10.0, 20.0]

    def test_soul(self) -> None:
        mon = FakeMonitor()
        mon._soul_text = "I monitor system health."
        assert mon.soul == "I monitor system health."

    def test_v1_compat_mcp_tools(self) -> None:
        """get_mcp_tools() returns MCP and ACTION powers as MCPToolDef objects."""
        mon = FakeMonitor()
        tools = mon.get_mcp_tools()
        names = [t.name for t in tools]
        assert "get_metrics" in names  # ACTION
        assert "get_cpu_raw" in names  # MCP
        assert "cpu" not in names  # COMMAND — not exposed as MCP

    def test_v1_compat_connector_commands(self) -> None:
        """get_connector_commands() returns only COMMAND powers as ConnectorCommand."""
        mon = FakeMonitor()
        commands = mon.get_connector_commands()
        assert len(commands) == 1
        assert commands[0].name == "cpu"

    def test_v1_compat_get_status(self) -> None:
        """get_status() delegates to get_pulse()."""
        mon = FakeMonitor()
        mon.activate({})
        assert mon.get_status() == {"cpu": 42.0, "memory": 65.0}


# ── PulseBus tests ──


class TestPulseBus:
    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self) -> None:
        bus = PulseBus.get()
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("source-1", "alert", handler)
        await bus.emit("source-1", "alert", {"level": "high"})
        assert received == [{"level": "high"}]

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = PulseBus.get()
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("source-1", "alert", handler)
        bus.unsubscribe("source-1", "alert", handler)
        await bus.emit("source-1", "alert", {"level": "high"})
        assert received == []

    def test_state_read_write(self) -> None:
        bus = PulseBus.get()
        bus.update_state("monitor", {"cpu": 50.0})
        assert bus.read_state("monitor") == {"cpu": 50.0}
        assert bus.read_state("nonexistent") == {}

    def test_clear_instance(self) -> None:
        bus = PulseBus.get()
        bus.update_state("monitor", {"cpu": 50.0})
        bus.clear_instance("monitor")
        assert bus.read_state("monitor") == {}


# ── MessageBus tests ──


class TestMessageBus:
    @pytest.mark.asyncio
    async def test_call_between_llmings(self) -> None:
        bus = MessageBus.get()
        mon = FakeMonitor()
        mon._instance_name = "monitor"
        mon.activate({})
        bus.register("monitor", mon)

        result = await bus.call("dashboard", "monitor", "cpu", {})
        assert result == "CPU: 42.0%"

    @pytest.mark.asyncio
    async def test_call_unknown_target(self) -> None:
        bus = MessageBus.get()
        with pytest.raises(ValueError, match="Unknown llming instance"):
            await bus.call("source", "nonexistent", "power", {})

    def test_register_unregister(self) -> None:
        bus = MessageBus.get()
        mon = FakeMonitor()
        bus.register("mon", mon)
        assert bus.get_instance("mon") is mon
        assert "mon" in bus.list_instances()
        bus.unregister("mon")
        assert bus.get_instance("mon") is None


# ── Inter-llming communication tests ──


class TestInterLlming:
    @pytest.mark.asyncio
    async def test_call_via_base(self) -> None:
        """LlmingBase.call() routes through the MessageBus."""
        bus = MessageBus.get()
        pulse = PulseBus.get()

        mon = FakeMonitor()
        mon._instance_name = "system-monitor"
        mon._pulse_bus = pulse
        mon.activate({})
        bus.register("system-monitor", mon)

        dash = FakeDashboard()
        dash._instance_name = "dashboard"
        dash._pulse_bus = pulse
        dash.activate({})
        bus.register("dashboard", dash)

        result = await dash.call("system-monitor", "get_cpu_raw")
        assert result == {"cpu_percent": 42.0}

    @pytest.mark.asyncio
    async def test_pulse_subscription(self) -> None:
        """Subscribe to another llming's pulse events via the bus."""
        pulse = PulseBus.get()

        mon = FakeMonitor()
        mon._instance_name = "system-monitor"
        mon._pulse_bus = pulse
        mon.activate({})

        dash = FakeDashboard()
        dash._instance_name = "dashboard"
        dash._pulse_bus = pulse
        dash.activate({})

        dash.subscribe("system-monitor", "cpu_spike", dash.on_spike)
        await mon.emit_pulse("cpu_spike", {"cpu": 95.0})
        assert dash.received_events == [{"cpu": 95.0}]

    @pytest.mark.asyncio
    async def test_read_pulse(self) -> None:
        """Read another llming's cached pulse state."""
        pulse = PulseBus.get()

        mon = FakeMonitor()
        mon._instance_name = "system-monitor"
        mon._pulse_bus = pulse
        mon.activate({})
        pulse.update_state("system-monitor", mon.get_pulse())

        dash = FakeDashboard()
        dash._instance_name = "dashboard"
        dash._pulse_bus = pulse

        state = await dash.read_pulse("system-monitor")
        assert state == {"cpu": 42.0, "memory": 65.0}


# ── LlmingRegistry tests ──


class TestLlmingRegistry:
    def _make_manifest(self, name: str = "test-monitor") -> ExtensionManifest:
        return ExtensionManifest(
            name=name,
            version="0.1.0",
            description="Test",
            entry_point="provider:FakeMonitor",
            path="/tmp/test",
        )

    def test_register_class(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        cls = LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
            soul_text="I monitor things.",
        )
        reg.register_class(cls)
        assert reg.get_class("test-monitor") is cls
        assert len(reg.list_classes()) == 1

    def test_create_instance(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        reg.register_class(LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
        ))

        inst = reg.create_instance("my-monitor", "test-monitor", {"threshold": 90})
        assert inst is not None
        assert inst.instance_name == "my-monitor"
        assert inst.class_name == "test-monitor"
        assert inst.config == {"threshold": 90}
        # Pulse should be populated after activate
        assert inst.get_pulse() == {"cpu": 42.0, "memory": 65.0}

    def test_singleton_enforcement(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        reg.register_class(LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
            singleton=True,
        ))

        inst1 = reg.create_instance("mon-1", "test-monitor")
        inst2 = reg.create_instance("mon-2", "test-monitor")
        assert inst1 is inst2  # same instance returned

    def test_multi_instance(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        reg.register_class(LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
            singleton=False,
        ))

        inst1 = reg.create_instance("mon-1", "test-monitor")
        inst2 = reg.create_instance("mon-2", "test-monitor")
        assert inst1 is not inst2

    def test_destroy_instance(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        reg.register_class(LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
        ))

        reg.create_instance("mon", "test-monitor")
        assert reg.get_instance("mon") is not None

        ok = reg.destroy_instance("mon")
        assert ok is True
        assert reg.get_instance("mon") is None
        assert reg.list_instances() == []

    def test_unknown_class(self) -> None:
        reg = LlmingRegistry.get()
        inst = reg.create_instance("x", "nonexistent")
        assert inst is None

    def test_services_injected(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        reg.register_class(LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
        ))

        inst = reg.create_instance("mon", "test-monitor")
        assert inst is not None
        assert inst._store is not None
        assert inst._files is not None
        assert inst._scheduler is not None
        assert inst._logger is not None
        assert inst._pulse_bus is not None

    def test_on_message_bus(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        reg.register_class(LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
        ))

        reg.create_instance("mon", "test-monitor")
        bus = MessageBus.get()
        assert bus.get_instance("mon") is not None

    def test_get_all_mcp_tools(self) -> None:
        reg = LlmingRegistry.get()
        manifest = self._make_manifest()
        reg.register_class(LlmingClass(
            name="test-monitor",
            manifest=manifest,
            python_class=FakeMonitor,
        ))
        reg.create_instance("mon", "test-monitor")

        tools = reg.get_all_mcp_tools()
        names = [t[1].name for t in tools]
        assert "get_metrics" in names
        assert "get_cpu_raw" in names
        assert "cpu" not in names  # COMMAND, not MCP
