"""Entry point: python -m subprojects.claude_chat"""

from __future__ import annotations

import argparse

from .chat import run_chat


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chat with Claude Code in the background",
    )
    parser.add_argument(
        "--model", "-m",
        help="Model to use (e.g. sonnet, opus, haiku)",
    )
    parser.add_argument(
        "--system", "-s",
        dest="system_prompt",
        help="System prompt for the conversation",
    )
    args = parser.parse_args()
    run_chat(model=args.model, system_prompt=args.system_prompt)


if __name__ == "__main__":
    main()
