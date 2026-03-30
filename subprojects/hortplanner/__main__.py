"""Run HortPlanner as a standalone server.

Usage:
    python -m subprojects.hortplanner
    python -m subprojects.hortplanner --port 8960
"""

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="HortPlanner Server")
    parser.add_argument("--port", type=int, default=8960, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    args = parser.parse_args()

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
