"""Run the MCP bridge as a standalone server.

Usage:
    # Stdio mode (for --mcp-config with command)
    python -m subprojects.mcp_bridge

    # SSE mode (for --mcp-config with url)
    python -m subprojects.mcp_bridge --sse --port 9100
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .bridge import MCPBridge, MCPSseServer, run_stdio
from .fake_plugins import FakeCalculatorPlugin, FakeMemoryPlugin


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Bridge Server")
    parser.add_argument("--sse", action="store_true", help="Run as SSE server instead of stdio")
    parser.add_argument("--port", type=int, default=9100, help="SSE server port")
    args = parser.parse_args()

    plugins = [FakeCalculatorPlugin(), FakeMemoryPlugin()]
    bridge = MCPBridge(plugins)

    if args.sse:
        async def run_sse() -> None:
            server = MCPSseServer(bridge, port=args.port)
            await server.start()
            print(f"MCP Bridge SSE server running on port {server.port}", file=sys.stderr)
            print(f"URL: {server.url}", file=sys.stderr)
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                pass
            finally:
                await server.stop()
        asyncio.run(run_sse())
    else:
        asyncio.run(run_stdio(bridge))


if __name__ == "__main__":
    main()
