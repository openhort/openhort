"""Llming implementations — NOT for import by the main hort process.

This package is imported ONLY by:
- Llming subprocesses (each llming runs in its own process)
- Tests (for unit testing llming code directly)

The main process (hort/) communicates with llmings via IPC only.
Direct imports from this package in hort/ code are a bug.
"""
