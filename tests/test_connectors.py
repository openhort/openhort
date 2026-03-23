"""Tests for connector framework — ConnectorMixin, CommandRegistry, ConnectorResponse."""

from __future__ import annotations

import pytest

from hort.ext.connectors import (
    CommandRegistry,
    ConnectorCapabilities,
    ConnectorCommand,
    ConnectorMixin,
    ConnectorResponse,
    IncomingMessage,
    ResponseButton,
)


class TestIncomingMessage:
    def test_command_parsing(self) -> None:
        msg = IncomingMessage(connector_id="test", chat_id="1", user_id="1", text="/cpu 42")
        assert msg.is_command is True
        assert msg.command == "cpu"
        assert msg.command_args == "42"

    def test_no_command(self) -> None:
        msg = IncomingMessage(connector_id="test", chat_id="1", user_id="1", text="hello")
        assert msg.is_command is False
        assert msg.command == ""
        assert msg.command_args == ""

    def test_command_with_bot_mention(self) -> None:
        msg = IncomingMessage(connector_id="test", chat_id="1", user_id="1", text="/help@mybot")
        assert msg.command == "help"

    def test_empty_text(self) -> None:
        msg = IncomingMessage(connector_id="test", chat_id="1", user_id="1")
        assert msg.is_command is False

    def test_command_no_args(self) -> None:
        msg = IncomingMessage(connector_id="test", chat_id="1", user_id="1", text="/status")
        assert msg.command == "status"
        assert msg.command_args == ""


class TestConnectorResponse:
    def test_simple(self) -> None:
        r = ConnectorResponse.simple("hello")
        assert r.text == "hello"
        assert r.image is None

    def test_with_image(self) -> None:
        r = ConnectorResponse.with_image(b"\xff\xd8", "caption")
        assert r.image == b"\xff\xd8"
        assert r.image_caption == "caption"
        assert r.text == "caption"


class TestConnectorCapabilities:
    def test_defaults(self) -> None:
        caps = ConnectorCapabilities()
        assert caps.text is True
        assert caps.markdown is False
        assert caps.images is False

    def test_telegram(self) -> None:
        caps = ConnectorCapabilities(text=True, markdown=True, html=True, images=True, inline_buttons=True)
        assert caps.html is True


class TestCommandRegistry:
    def test_register_system(self) -> None:
        reg = CommandRegistry()
        reg.register_system([ConnectorCommand(name="help", description="Help", system=True)])
        result = reg.get_command("help")
        assert result is not None
        assert result[1].system is True

    def test_system_cannot_be_overridden(self) -> None:
        reg = CommandRegistry()
        reg.register_system([ConnectorCommand(name="help", description="System help", system=True)])

        class FakePlugin(ConnectorMixin):
            pass

        reg.register_plugin("my-plugin", FakePlugin(), [ConnectorCommand(name="help", description="Plugin help")])
        result = reg.get_command("help")
        assert result is not None
        assert result[1].description == "System help"  # system wins

    def test_plugin_command(self) -> None:
        reg = CommandRegistry()

        class FakePlugin(ConnectorMixin):
            pass

        reg.register_plugin("sys-mon", FakePlugin(), [ConnectorCommand(name="cpu", description="CPU usage")])
        result = reg.get_command("cpu")
        assert result is not None
        assert result[0] == "sys-mon"

    def test_unknown_command(self) -> None:
        reg = CommandRegistry()
        assert reg.get_command("nope") is None

    def test_get_all_commands(self) -> None:
        reg = CommandRegistry()
        reg.register_system([ConnectorCommand(name="help", description="Help", system=True)])

        class FakePlugin(ConnectorMixin):
            pass

        reg.register_plugin("p", FakePlugin(), [
            ConnectorCommand(name="cpu", description="CPU"),
            ConnectorCommand(name="secret", description="Hidden", hidden=True),
        ])
        cmds = reg.get_all_commands()
        names = [c.name for c in cmds]
        assert "help" in names
        assert "cpu" in names
        assert "secret" not in names  # hidden

    async def test_dispatch_plugin_command(self) -> None:
        reg = CommandRegistry()

        class MyPlugin(ConnectorMixin):
            async def handle_connector_command(self, command, message, caps):
                return ConnectorResponse.simple(f"handled: {command}")

        reg.register_plugin("p", MyPlugin(), [ConnectorCommand(name="test", description="Test")])
        msg = IncomingMessage(connector_id="t", chat_id="1", user_id="1", text="/test")
        result = await reg.dispatch(msg, ConnectorCapabilities())
        assert result is not None
        assert "handled: test" in (result.text or "")

    async def test_dispatch_unknown(self) -> None:
        reg = CommandRegistry()
        msg = IncomingMessage(connector_id="t", chat_id="1", user_id="1", text="/nope")
        result = await reg.dispatch(msg, ConnectorCapabilities())
        assert result is not None
        assert "Unknown command" in (result.text or "")

    async def test_dispatch_system_returns_none(self) -> None:
        reg = CommandRegistry()
        reg.register_system([ConnectorCommand(name="help", description="Help", system=True)])
        msg = IncomingMessage(connector_id="t", chat_id="1", user_id="1", text="/help")
        result = await reg.dispatch(msg, ConnectorCapabilities())
        assert result is None  # system commands handled by connector itself


    async def test_dispatch_non_command(self) -> None:
        reg = CommandRegistry()
        msg = IncomingMessage(connector_id="t", chat_id="1", user_id="1", text="hello")
        result = await reg.dispatch(msg, ConnectorCapabilities())
        assert result is None

    async def test_dispatch_plugin_not_found(self) -> None:
        reg = CommandRegistry()

        class FakePlugin(ConnectorMixin):
            pass

        reg.register_plugin("ghost", FakePlugin(), [ConnectorCommand(name="ghost", description="Gone")])
        # Remove the plugin but leave the command registered
        del reg._plugins["ghost"]
        msg = IncomingMessage(connector_id="t", chat_id="1", user_id="1", text="/ghost")
        result = await reg.dispatch(msg, ConnectorCapabilities())
        assert result is not None
        assert "not available" in (result.text or "")


class TestConnectorBase:
    def test_render_text_html(self) -> None:
        from hort.ext.connectors import ConnectorBase

        class FakeConnector(ConnectorBase):
            @property
            def connector_id(self) -> str:
                return "fake"

            @property
            def capabilities(self) -> ConnectorCapabilities:
                return ConnectorCapabilities(text=True, html=True, markdown=True)

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
                pass

        c = FakeConnector()
        r = ConnectorResponse(text="plain", markdown="**bold**", html="<b>bold</b>")
        assert c.render_text(r) == "<b>bold</b>"

    def test_render_text_markdown(self) -> None:
        from hort.ext.connectors import ConnectorBase

        class FakeConnector(ConnectorBase):
            @property
            def connector_id(self) -> str:
                return "fake"

            @property
            def capabilities(self) -> ConnectorCapabilities:
                return ConnectorCapabilities(text=True, markdown=True)

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
                pass

        c = FakeConnector()
        r = ConnectorResponse(text="plain", markdown="**bold**")
        assert c.render_text(r) == "**bold**"

    def test_render_text_plain(self) -> None:
        from hort.ext.connectors import ConnectorBase

        class FakeConnector(ConnectorBase):
            @property
            def connector_id(self) -> str:
                return "fake"

            @property
            def capabilities(self) -> ConnectorCapabilities:
                return ConnectorCapabilities(text=True)

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_response(self, chat_id: str, response: ConnectorResponse) -> None:
                pass

        c = FakeConnector()
        r = ConnectorResponse(text="plain", markdown="**bold**")
        assert c.render_text(r) == "plain"


class TestConnectorMixin:
    def test_default_get_commands(self) -> None:
        mixin = ConnectorMixin()
        assert mixin.get_connector_commands() == []

    async def test_default_handle_returns_none(self) -> None:
        mixin = ConnectorMixin()
        msg = IncomingMessage(connector_id="t", chat_id="1", user_id="1", text="/test")
        result = await mixin.handle_connector_command("test", msg, ConnectorCapabilities())
        assert result is None
