"""Envoy — the execution agent inside sandbox containers.

The Envoy runs as a local MCP stdio server inside the container.
Claude Code connects to it via stdin/stdout (no network).
The host pushes tool definitions and handles tool calls via
a control channel (TCP socket through docker exec).

See docs/manual/internals/envoy-architecture.md for the full design.
"""
