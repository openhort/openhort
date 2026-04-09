"""MCP bridge — serves llming tools over Model Context Protocol.

The bridge aggregates tools from all llmings and exposes them via
stdio or SSE transport for Claude Code (local or containerized).
"""

from hort.mcp.bridge import MCPBridge, MCPSseServer, run_stdio

__all__ = ["MCPBridge", "MCPSseServer", "run_stdio"]
