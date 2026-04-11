"""Container entrypoint — runs llming-models inside a sandbox.

Invoked via ``docker exec`` with the prompt as arguments.
Streams JSON lines to stdout (same protocol as Claude CLI for
compatibility with the typewriter display).

Protocol (stdout, newline-delimited JSON):
    {"type": "text", "content": "chunk"}
    {"type": "meta", "conversation_id": "abc", "cost": 0.01}

API key is available via ANTHROPIC_API_KEY env var (injected at
container creation, never written to disk).
"""

from __future__ import annotations

import asyncio
import json
import sys


async def _run(model: str, prompt: str, system_prompt: str | None) -> None:
    from llming_models import LLMManager

    manager = LLMManager()
    session = manager.create_session(
        model=model,
        system_prompt=system_prompt or "",
    )

    stream = await session.chat_async(prompt, streaming=True)
    async for chunk in stream:
        if chunk.content:
            line = json.dumps({"type": "text", "content": chunk.content})
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    sys.stdout.write(json.dumps({"type": "meta"}) + "\n")
    sys.stdout.flush()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--model", default="claude_sonnet")
    parser.add_argument("--system-prompt", default=None)
    args = parser.parse_args()

    asyncio.run(_run(args.model, args.prompt, args.system_prompt))


if __name__ == "__main__":
    main()
