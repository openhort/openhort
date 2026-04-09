"""API authentication middleware — protects all sensitive REST endpoints.

Two tiers:
- **Localhost**: Trusted for statusbar and dev tools. Statusbar uses shared
  key file auth (X-Hort-Key header). No brute-force on localhost.
- **Remote**: Session token required (llming-com HMAC-signed). Brute-force
  detection per IP (5 failures in 60s → 429).

The SPA uses the authenticated WebSocket for all data. These REST endpoints
exist for future admin API / external integrations.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("hort.auth")

# Paths that never require authentication (any source)
PUBLIC_PATHS = (
    "/api/hash",          # health check (no secrets)
    "/api/session",       # session creation (entry point)
    "/api/icon/",         # static asset
    "/api/qr",            # pairing QR
    "/_internal/",        # cloud proxy internal
    "/auth/callback",     # OAuth redirect
)

# Localhost IPs — statusbar and dev tools come from here
_LOCALHOST = {"127.0.0.1", "::1", "localhost"}

# Non-API paths are always public (SPA, static, WebSocket, etc.)
_API_PREFIX = "/api/"

# Brute-force limits (remote only — localhost is exempt)
_MAX_FAILURES = 5
_WINDOW_SECONDS = 60


class _BruteForceTracker:
    """Track failed auth attempts per remote IP."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = defaultdict(list)

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        self._failures[ip].append(now)
        cutoff = now - _WINDOW_SECONDS
        self._failures[ip] = [t for t in self._failures[ip] if t > cutoff]

    def is_blocked(self, ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        attempts = [t for t in self._failures.get(ip, []) if t > cutoff]
        return len(attempts) >= _MAX_FAILURES

    def clear(self, ip: str) -> None:
        self._failures.pop(ip, None)


_tracker = _BruteForceTracker()


def _is_localhost(request: Request) -> bool:
    """Check if the request comes from localhost."""
    if request.client:
        return request.client.host in _LOCALHOST
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Protect /api/ routes with session auth + brute-force detection.

    Localhost is trusted (statusbar, dev tools) — no brute-force tracking.
    Remote requests require a valid session token.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path

        async def _next() -> Response:
            response: Response = await call_next(request)
            return response

        # WebSocket upgrades are NOT handled by HTTP middleware —
        # they have their own auth (session lookup in the WS handler).
        # BaseHTTPMiddleware + WebSocket = broken in Starlette.
        if request.scope.get("type") == "websocket":
            return await _next()

        # Non-API paths are always public
        if not path.startswith(_API_PREFIX):
            return await _next()

        # Public API endpoints (any source)
        for prefix in PUBLIC_PATHS:
            if path.startswith(prefix):
                return await _next()

        # Localhost is trusted — statusbar, dev tools, SPA during development
        if _is_localhost(request):
            return await _next()

        # Remote requests: brute-force check
        client_ip = request.client.host if request.client else "unknown"
        if _tracker.is_blocked(client_ip):
            return JSONResponse(
                {"error": "Too many failed attempts. Try again later."},
                status_code=429,
            )

        # Session auth via llming-com
        from hort.session import HortSessionManager
        manager = HortSessionManager.get()
        session_id, entry = manager.resolve(request)

        if entry is None:
            _tracker.record_failure(client_ip)
            return JSONResponse(
                {"error": "Authentication required"},
                status_code=401,
            )

        # Valid session — clear any failure count
        _tracker.clear(client_ip)
        return await _next()
