"""Auth gate: protect every /api/* route except an explicit public allowlist.

Protected-by-default — any new router under /api is gated automatically. The
allowlist is the auth endpoints, the public observability surface, and the
unprefixed /health probe.

Localhost/dev bypass: when ZENGROWTH_REQUIRE_HTTPS is off and the request comes
from loopback (or Starlette's TestClient host), requests pass through without a
session. That keeps local dev and the test suite working without a configured
operator. Production sets ZENGROWTH_REQUIRE_HTTPS=true, disabling the bypass.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import get_settings
from .routers.auth import LOOPBACK_HOSTS, SESSION_COOKIE
from .security import verify_session_cookie

_PUBLIC_PREFIXES = ("/api/auth/", "/api/public/")
_LOOPBACK_HOSTS = LOOPBACK_HOSTS


def _is_allowlisted(path: str) -> bool:
    if path == "/health":
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or _is_allowlisted(path):
            return await call_next(request)

        settings = get_settings()

        client_host = request.client.host if request.client else None
        if not settings.zengrowth_require_https and client_host in _LOOPBACK_HOSTS:
            return await call_next(request)

        secret = settings.zengrowth_session_secret
        cookie = request.cookies.get(SESSION_COOKIE)
        if secret and cookie and verify_session_cookie(secret, cookie):
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "not authenticated"})
