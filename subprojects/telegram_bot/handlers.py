"""Telegram command handlers — the bot's user-facing commands."""

from __future__ import annotations

import io
import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .hort_client import HortClient

logger = logging.getLogger(__name__)

router = Router(name="handlers")


def _get_client(data: dict) -> HortClient:
    return data["hort_client"]


# ── /start ──────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "OpenHORT remote viewer bot.\n\n"
        "Commands:\n"
        "/windows — list windows\n"
        "/screenshot <app> — capture a window\n"
        "/targets — list targets\n"
        "/status — server status\n"
        "/spaces — list virtual desktops\n"
        "/run <cmd> — execute a shell command"
    )


# ── /status ─────────────────────────────────────────────


@router.message(Command("status"))
async def cmd_status(message: Message, hort_client: HortClient) -> None:
    try:
        status = await hort_client.get_status()
        observers = status.get("observers", "?")
        version = status.get("version", "?")
        await message.answer(f"Observers: {observers}\nVersion: {version}")
    except Exception as e:
        await message.answer(f"Error: {e}")


# ── /targets ────────────────────────────────────────────


@router.message(Command("targets"))
async def cmd_targets(message: Message, hort_client: HortClient) -> None:
    try:
        targets = await hort_client.list_targets()
        if not targets:
            await message.answer("No targets connected.")
            return
        lines = []
        for t in targets:
            status_icon = "+" if t.get("status") == "online" else "-"
            lines.append(f"[{status_icon}] {t['name']} ({t['id']})")
        await message.answer("\n".join(lines))
    except Exception as e:
        await message.answer(f"Error: {e}")


# ── /windows ────────────────────────────────────────────


@router.message(Command("windows"))
async def cmd_windows(message: Message, hort_client: HortClient) -> None:
    try:
        args = (message.text or "").split(maxsplit=1)
        app_filter = args[1] if len(args) > 1 else ""
        windows = await hort_client.list_windows(app_filter=app_filter)
        if not windows:
            await message.answer("No windows found.")
            return

        # Build inline keyboard — one button per window (max 20)
        buttons = []
        for w in windows[:20]:
            label = f"{w['owner_name']}: {w.get('window_name', '')}"[:40]
            cb_data = f"thumb:{w['window_id']}:{w.get('target_id', '')}"
            # Callback data max 64 bytes
            if len(cb_data.encode()) <= 64:
                buttons.append(
                    [InlineKeyboardButton(text=label, callback_data=cb_data)]
                )

        if buttons:
            await message.answer(
                f"{len(windows)} window(s) — tap to screenshot:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
        else:
            lines = [
                f"- {w['owner_name']}: {w.get('window_name', '')}"
                for w in windows[:20]
            ]
            await message.answer("\n".join(lines))
    except Exception as e:
        await message.answer(f"Error: {e}")


# ── Callback: thumbnail from /windows ───────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("thumb:"))
async def cb_thumbnail(callback: CallbackQuery, hort_client: HortClient) -> None:
    assert callback.data is not None
    parts = callback.data.split(":", 2)
    window_id = int(parts[1])
    target_id = parts[2] if len(parts) > 2 and parts[2] else None

    await callback.answer("Capturing...")

    try:
        jpeg = await hort_client.get_thumbnail(window_id, target_id=target_id)
        if jpeg:
            photo = BufferedInputFile(jpeg, filename="screenshot.jpg")
            assert callback.message is not None
            await callback.message.answer_photo(photo=photo)
        else:
            assert callback.message is not None
            await callback.message.answer("Capture failed — window may have closed.")
    except Exception as e:
        if callback.message:
            await callback.message.answer(f"Error: {e}")


# ── /screenshot ─────────────────────────────────────────


@router.message(Command("screenshot"))
async def cmd_screenshot(message: Message, hort_client: HortClient) -> None:
    args = (message.text or "").split(maxsplit=1)
    app_filter = args[1] if len(args) > 1 else ""

    try:
        windows = await hort_client.list_windows(app_filter=app_filter)
        if not windows:
            await message.answer("No matching windows.")
            return

        # Screenshot the first matching window
        w = windows[0]
        jpeg = await hort_client.get_thumbnail(
            w["window_id"], target_id=w.get("target_id")
        )
        if jpeg:
            caption = f"{w['owner_name']}: {w.get('window_name', '')}"[:1024]
            photo = BufferedInputFile(jpeg, filename="screenshot.jpg")
            await message.answer_photo(photo=photo, caption=caption)
        else:
            await message.answer("Capture failed.")
    except Exception as e:
        await message.answer(f"Error: {e}")


# ── /spaces ─────────────────────────────────────────────


@router.message(Command("spaces"))
async def cmd_spaces(message: Message, hort_client: HortClient) -> None:
    try:
        data = await hort_client.get_spaces()
        spaces = data.get("spaces", [])
        if not spaces:
            await message.answer("No spaces info available.")
            return

        buttons = []
        for s in spaces:
            idx = s["index"]
            cur = " (current)" if s.get("is_current") else ""
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"Space {idx}{cur}",
                        callback_data=f"space:{idx}",
                    )
                ]
            )
        await message.answer(
            f"{len(spaces)} space(s) — tap to switch:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception as e:
        await message.answer(f"Error: {e}")


@router.callback_query(lambda c: c.data and c.data.startswith("space:"))
async def cb_switch_space(callback: CallbackQuery, hort_client: HortClient) -> None:
    assert callback.data is not None
    idx = int(callback.data.split(":")[1])
    try:
        result = await hort_client.switch_space(idx)
        ok = result.get("ok", False)
        await callback.answer(f"Switched to space {idx}" if ok else "Switch failed")
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)


# ── /run ────────────────────────────────────────────────


@router.message(Command("run"))
async def cmd_run(message: Message, hort_client: HortClient) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /run <command>")
        return

    cmd = args[1]
    # Safety: reject obviously dangerous commands
    dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb"]
    if any(d in cmd.lower() for d in dangerous):
        await message.answer("Refused: potentially destructive command.")
        return

    try:
        # Use hort's terminal: spawn, wait for output, close
        # For simplicity, use a short-lived approach via the command target
        resp = await hort_client._request(
            "terminal_spawn", command=f"bash -c {_shell_quote(cmd)}"
        )
        terminal_id = resp.get("terminal_id")
        if not terminal_id:
            await message.answer("Failed to spawn terminal.")
            return

        # Give the command time to produce output, then read scrollback
        # Terminal I/O goes over a separate binary WS which we don't connect to
        # So we just confirm the spawn
        await message.answer(
            f"Terminal spawned: {terminal_id}\n"
            f"Command: {cmd}\n\n"
            "Note: Full terminal I/O requires the Mini App viewer. "
            "This command started a session you can connect to."
        )
    except Exception as e:
        await message.answer(f"Error: {e}")


def _shell_quote(s: str) -> str:
    """Simple shell quoting."""
    return "'" + s.replace("'", "'\\''") + "'"
