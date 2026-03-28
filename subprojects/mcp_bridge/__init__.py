"""MCP Bridge — exposes in-process MCPMixin plugins as MCP protocol servers.

Bridges the gap between openhort's plugin MCPMixin interface and the MCP
protocol (stdio + SSE transports), so Claude Code can use plugin tools
via --mcp-config.
"""
