"""Entry point: python -m subprojects.telegram_bot"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Load .env from project root
_root = Path(__file__).resolve().parent.parent.parent
_env_file = _root / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            import os

            os.environ.setdefault(key.strip(), val.strip())

from .bot import run_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
