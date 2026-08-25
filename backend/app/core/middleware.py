"""Response hardening.

This service is a JSON API plus provider redirects; it never renders HTML and is
never a legitimate frame. The headers say so, so a browser refuses the classes of
attack that rely on it being either.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # An API that serves no markup and loads nothing needs nothing.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

HSTS = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in BASE_HEADERS.items():
            response.headers.setdefault(header, value)
        # Only meaningful over TLS, and asserting it in local http development
        # would pin the browser to https://localhost for a year.
        if get_settings().cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response
