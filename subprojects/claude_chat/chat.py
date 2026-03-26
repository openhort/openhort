"""Main chat loop — read user input, spawn Claude, display response."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile

from .typewriter import typewriter

# Appended to every session so Claude outputs plain text, not markdown
_PLAIN_TEXT_INSTRUCTION = (
    "You are in a plain terminal chat. Do not use markdown formatting: "
    "no >, **, `, #, or other markdown syntax. Use plain text only."
)


def _build_args(
    user_input: str,
    *,
    model: str | None,
    system_prompt: str | None,
    session_id: str | None,
    turn_count: int,
    container: bool,
) -> list[str]:
    """Build the argument list for ``claude -p``."""
    args: list[str] = [
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--dangerously-skip-permissions",
    ]
    # Inside a container we must use --bare so auth falls through
    # to ANTHROPIC_API_KEY (no keychain available).
    if container:
        args.append("--bare")
    if model:
        args.extend(["--model", model])
    if system_prompt and turn_count == 0:
        args.extend(["--system-prompt", system_prompt])
    if turn_count == 0:
        args.extend(["--append-system-prompt", _PLAIN_TEXT_INSTRUCTION])
    if session_id:
        args.extend(["--resume", session_id])
    args.append(user_input)
    return args


def run_chat(
    model: str | None = None,
    system_prompt: str | None = None,
    container: bool = False,
) -> None:
    """Interactive chat loop.

    Each user message spawns a ``claude -p`` subprocess.  Conversation
    continuity is maintained via ``--resume <session_id>``.

    When *container* is True, Claude runs inside a Docker sandbox
    with auth injected from the macOS Keychain.
    """
    # ── Container setup ─────────────────────────────────────────────
    if container:
        from .container import (
            build_image,
            ensure_container,
            get_oauth_token,
            image_exists,
            stop_container,
        )

        token = get_oauth_token()
        if not image_exists():
            build_image()
        ensure_container(token)

    tmpdir = tempfile.mkdtemp(prefix="claude-chat-")
    session_id: str | None = None
    total_cost = 0.0
    turn_count = 0

    print("\033[1mClaude Chat\033[0m", end="")
    if container:
        print("  \033[33m[container]\033[0m", end="")
    print()
    if not container:
        print(f"Temp dir: {tmpdir}")
    if model:
        print(f"Model: {model}")
    print("Type 'exit' or Ctrl-C to quit.\n")

    def cleanup(sig: int = 0, frame: object = None) -> None:
        print("\n\nGoodbye!")
        if total_cost > 0:
            print(f"Session cost: ${total_cost:.4f} ({turn_count} turns)")
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)

    while True:
        try:
            user_input = input("\033[1;32myou>\033[0m ")
        except (EOFError, KeyboardInterrupt):
            cleanup()
            return

        stripped = user_input.strip()
        if stripped.lower() in ("exit", "quit"):
            cleanup()
            return

        if not stripped:
            continue

        # ── Build args and spawn ────────────────────────────────────
        args = _build_args(
            user_input,
            model=model,
            system_prompt=system_prompt,
            session_id=session_id,
            turn_count=turn_count,
            container=container,
        )

        if container:
            from .container import exec_claude
            proc = exec_claude(args)
        else:
            proc = subprocess.Popen(
                ["claude", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                cwd=tmpdir,
            )

        print("\033[1;34mclaude>\033[0m ", end="", flush=True)

        meta = typewriter(proc)
        if meta.get("session_id"):
            session_id = meta["session_id"]
        total_cost += meta.get("cost", 0)
        turn_count += 1
