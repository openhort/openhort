"""Tests for Telegram command handlers — uses aiogram's test utilities."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from subprojects.telegram_bot.handlers import (
    cmd_screenshot,
    cmd_spaces,
    cmd_start,
    cmd_status,
    cmd_targets,
    cmd_windows,
    cb_thumbnail,
    cmd_run,
)


def _mock_message(text: str = "") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()
    return msg


def _mock_callback(data: str) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    cb.message.answer_photo = AsyncMock()
    return cb


def _mock_hort_client() -> MagicMock:
    client = MagicMock()
    client.list_targets = AsyncMock(
        return_value=[
            {"id": "local-macos", "name": "This Mac", "status": "online"}
        ]
    )
    client.list_windows = AsyncMock(
        return_value=[
            {
                "window_id": 42,
                "owner_name": "Finder",
                "window_name": "Documents",
                "target_id": "local-macos",
            }
        ]
    )
    client.get_thumbnail = AsyncMock(return_value=b"\xff\xd8fake-jpeg")
    client.get_status = AsyncMock(
        return_value={"observers": 2, "version": "0.1.0", "type": "status"}
    )
    client.get_spaces = AsyncMock(
        return_value={
            "spaces": [
                {"index": 1, "is_current": True},
                {"index": 2, "is_current": False},
            ],
            "current": 1,
            "count": 2,
        }
    )
    client.switch_space = AsyncMock(return_value={"ok": True, "target": 2})
    client._request = AsyncMock(
        return_value={"terminal_id": "term-1"}
    )
    return client


class TestStartCommand:
    @pytest.mark.asyncio
    async def test_start(self) -> None:
        msg = _mock_message("/start")
        await cmd_start(msg)
        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "OpenHORT" in text
        assert "/windows" in text


class TestStatusCommand:
    @pytest.mark.asyncio
    async def test_status(self) -> None:
        msg = _mock_message("/status")
        client = _mock_hort_client()
        await cmd_status(msg, hort_client=client)
        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "Observers: 2" in text
        assert "Version: 0.1.0" in text

    @pytest.mark.asyncio
    async def test_status_error(self) -> None:
        msg = _mock_message("/status")
        client = _mock_hort_client()
        client.get_status = AsyncMock(side_effect=ConnectionError("nope"))
        await cmd_status(msg, hort_client=client)
        text = msg.answer.call_args[0][0]
        assert "Error" in text


class TestTargetsCommand:
    @pytest.mark.asyncio
    async def test_targets(self) -> None:
        msg = _mock_message("/targets")
        client = _mock_hort_client()
        await cmd_targets(msg, hort_client=client)
        text = msg.answer.call_args[0][0]
        assert "This Mac" in text
        assert "[+]" in text

    @pytest.mark.asyncio
    async def test_no_targets(self) -> None:
        msg = _mock_message("/targets")
        client = _mock_hort_client()
        client.list_targets = AsyncMock(return_value=[])
        await cmd_targets(msg, hort_client=client)
        text = msg.answer.call_args[0][0]
        assert "No targets" in text


class TestWindowsCommand:
    @pytest.mark.asyncio
    async def test_windows(self) -> None:
        msg = _mock_message("/windows")
        client = _mock_hort_client()
        await cmd_windows(msg, hort_client=client)
        msg.answer.assert_called_once()
        call_kwargs = msg.answer.call_args[1]
        assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_windows_with_filter(self) -> None:
        msg = _mock_message("/windows Finder")
        client = _mock_hort_client()
        await cmd_windows(msg, hort_client=client)
        client.list_windows.assert_called_once_with(app_filter="Finder")

    @pytest.mark.asyncio
    async def test_no_windows(self) -> None:
        msg = _mock_message("/windows")
        client = _mock_hort_client()
        client.list_windows = AsyncMock(return_value=[])
        await cmd_windows(msg, hort_client=client)
        text = msg.answer.call_args[0][0]
        assert "No windows" in text


class TestScreenshotCommand:
    @pytest.mark.asyncio
    async def test_screenshot(self) -> None:
        msg = _mock_message("/screenshot Finder")
        client = _mock_hort_client()
        await cmd_screenshot(msg, hort_client=client)
        msg.answer_photo.assert_called_once()
        call_kwargs = msg.answer_photo.call_args[1]
        assert "caption" in call_kwargs
        assert "Finder" in call_kwargs["caption"]

    @pytest.mark.asyncio
    async def test_screenshot_no_match(self) -> None:
        msg = _mock_message("/screenshot NonExistent")
        client = _mock_hort_client()
        client.list_windows = AsyncMock(return_value=[])
        await cmd_screenshot(msg, hort_client=client)
        msg.answer.assert_called_once()
        assert "No matching" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_screenshot_capture_failed(self) -> None:
        msg = _mock_message("/screenshot")
        client = _mock_hort_client()
        client.get_thumbnail = AsyncMock(return_value=None)
        await cmd_screenshot(msg, hort_client=client)
        assert "Capture failed" in msg.answer.call_args[0][0]


class TestThumbnailCallback:
    @pytest.mark.asyncio
    async def test_thumbnail_callback(self) -> None:
        cb = _mock_callback("thumb:42:local-macos")
        client = _mock_hort_client()
        await cb_thumbnail(cb, hort_client=client)
        cb.answer.assert_called_once_with("Capturing...")
        cb.message.answer_photo.assert_called_once()

    @pytest.mark.asyncio
    async def test_thumbnail_failed(self) -> None:
        cb = _mock_callback("thumb:42:local-macos")
        client = _mock_hort_client()
        client.get_thumbnail = AsyncMock(return_value=None)
        await cb_thumbnail(cb, hort_client=client)
        assert "failed" in cb.message.answer.call_args[0][0].lower()


class TestSpacesCommand:
    @pytest.mark.asyncio
    async def test_spaces(self) -> None:
        msg = _mock_message("/spaces")
        client = _mock_hort_client()
        await cmd_spaces(msg, hort_client=client)
        call_kwargs = msg.answer.call_args[1]
        assert "reply_markup" in call_kwargs


class TestRunCommand:
    @pytest.mark.asyncio
    async def test_run_no_args(self) -> None:
        msg = _mock_message("/run")
        client = _mock_hort_client()
        await cmd_run(msg, hort_client=client)
        assert "Usage" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_dangerous(self) -> None:
        msg = _mock_message("/run rm -rf /")
        client = _mock_hort_client()
        await cmd_run(msg, hort_client=client)
        assert "Refused" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_spawns_terminal(self) -> None:
        msg = _mock_message("/run ls -la")
        client = _mock_hort_client()
        await cmd_run(msg, hort_client=client)
        client._request.assert_called_once()
        assert "term-1" in msg.answer.call_args[0][0]
