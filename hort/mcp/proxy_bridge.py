"""MCP proxy bridge — thin proxy that routes tool calls to the main server.

The bridge subprocess does NOT load any extensions, does NOT import
Quartz/pyobjc, does NOT instantiate llmings. It:

1. Fetches tool definitions from GET /api/debug/tools (one HTTP call)
2. Exposes them as MCP tools via SSE transport
3. Routes tool calls to POST /api/debug/call on the main server

This is the ONLY correct way to run the MCP bridge. Never load
extensions in a subprocess — they duplicate state, leak native memory,
and diverge from the main server's llming instances.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

_SERVER_URL = "http://localhost:8940"


class _ProxyProvider:
    """Single MCP provider that proxies ALL tool calls to the main server."""

    def __init__(self, server_url: str, tools: list[dict[str, Any]]) -> None:
        self._server_url = server_url
        self._tools = tools
        self._routing: dict[str, tuple[str, str]] = {}
        for t in tools:
            self._routing[t["name"]] = (t["_llming"], t["_power"])

    @property
    def plugin_id(self) -> str:
        return "openhort"

    def get_mcp_tools(self) -> list[Any]:
        from hort.ext.mcp import MCPToolDef
        return [
            MCPToolDef(
                name=f"{t['_llming']}__{t['_power']}",
                description=f"[{t['_llming']}] {t['description']}",
                input_schema=t.get("inputSchema", {}),
            )
            for t in self._tools
        ]

    async def execute_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        import httpx
        from hort.ext.mcp import MCPToolResult

        # Parse llming__power from the namespaced tool name
        if "__" in tool_name:
            llming_name, power_name = tool_name.split("__", 1)
        else:
            route = self._routing.get(tool_name)
            if not route:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                    is_error=True,
                )
            llming_name, power_name = route

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._server_url}/api/debug/call",
                    json={"llming": llming_name, "power": power_name, "args": arguments},
                )
                data = resp.json()

                if "error" in data:
                    return MCPToolResult(
                        content=[{"type": "text", "text": data["error"]}],
                        is_error=True,
                    )

                result = data.get("result", {})
                if isinstance(result, dict) and "content" in result:
                    return MCPToolResult(
                        content=result["content"],
                        is_error=result.get("is_error", False),
                    )
                if isinstance(result, str):
                    return MCPToolResult(content=[{"type": "text", "text": result}])
                return MCPToolResult(content=[{"type": "text", "text": json.dumps(result)}])

        except Exception as exc:
            return MCPToolResult(
                content=[{"type": "text", "text": f"Server error: {exc}"}],
                is_error=True,
            )


def fetch_tools(server_url: str = _SERVER_URL, retries: int = 30) -> list[dict[str, Any]]:
    """Fetch all MCP tool definitions from the main server.

    Retries until the server is ready (it starts in parallel with the bridge).
    """
    import time
    import httpx as _httpx

    for i in range(retries):
        try:
            resp = _httpx.get(f"{server_url}/api/debug/tools", timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        if i < retries - 1:
            time.sleep(1)
            if i == 0:
                logger.info("Waiting for main server...")
    logger.error("Failed to fetch tools after %d retries", retries)
    return []


def run_proxy_bridge(
    server_url: str = _SERVER_URL,
    mode: str = "sse",
    port: int = 0,
) -> None:
    """Start the proxy MCP bridge.

    Starts the SSE server immediately (so the parent process unblocks),
    then fetches tools from the main server in the background.
    """
    import asyncio
    from hort.mcp.bridge import MCPBridge, MCPSseServer, run_stdio

    # Start with empty provider — tools loaded after server is ready
    provider = _ProxyProvider(server_url, [])
    bridge = MCPBridge([provider])

    if mode == "sse":
        loop = asyncio.new_event_loop()
        server = MCPSseServer(bridge, port=port)
        loop.run_until_complete(server.start())
        logger.info("MCP bridge SSE server on port %d", server.port)
        logger.info("SSE server: http://localhost:%d/sse", server.port)
        logger.info("Container URL: http://host.docker.internal:%d/sse", server.port)

        # Fetch tools in background (main server may not be ready yet)
        async def _load_tools() -> None:
            tools = await asyncio.get_event_loop().run_in_executor(None, fetch_tools, server_url)
            provider._tools = tools
            provider._routing = {}
            for t in tools:
                provider._routing[f"{t['_llming']}__{t['_power']}"] = (t["_llming"], t["_power"])
            # Rebuild bridge's provider cache
            bridge._providers = {provider.plugin_id: provider}
            logger.info("Bridge ready: %d tools from %s", len(tools), server_url)

        loop.create_task(_load_tools())
        loop.run_forever()
    else:
        asyncio.run(run_stdio(bridge))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    port = 0
    mode = "sse"
    server = _SERVER_URL
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])
        elif arg == "--stdio":
            mode = "stdio"
        elif arg == "--server" and i < len(sys.argv) - 1:
            server = sys.argv[i + 1]
    run_proxy_bridge(server_url=server, mode=mode, port=port)
