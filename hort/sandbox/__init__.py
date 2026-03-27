"""Reusable isolated execution sessions backed by Docker.

Core infrastructure for running commands in sandboxed containers with
resource limits, persistent workspace volumes, MCP server integration,
and automatic lifecycle cleanup.

Quick start::

    from hort.sandbox import SessionManager, SessionConfig

    mgr = SessionManager()
    session = mgr.create(SessionConfig(memory="1g", cpus=2))
    session.start()
    result = session.exec(["echo", "hello"], capture_output=True, text=True)
    session.stop()   # preserves workspace for resume
    session.destroy() # removes everything
"""

from .session import (
    BASE_DOCKERFILE_DIR,
    BASE_IMAGE,
    CONTAINER_PREFIX,
    DEFAULT_IMAGE,
    DEFAULT_STORE,
    VOLUME_PREFIX,
    Session,
    SessionConfig,
    SessionManager,
    SessionMeta,
)

__all__ = [
    "BASE_DOCKERFILE_DIR",
    "BASE_IMAGE",
    "CONTAINER_PREFIX",
    "DEFAULT_IMAGE",
    "DEFAULT_STORE",
    "VOLUME_PREFIX",
    "Session",
    "SessionConfig",
    "SessionManager",
    "SessionMeta",
]
