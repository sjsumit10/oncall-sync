"""Session and CSRF cookie handling."""

from fastapi import Response

from app.config import get_settings
from app.core.sessions import CSRF_COOKIE, SESSION_COOKIE, SESSION_TTL


def set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    secure = settings.cookie_secure
    max_age = int(SESSION_TTL.total_seconds())

    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    # Readable by JavaScript on purpose: the SPA echoes it back in X-CSRF-Token,
    # which is the half of the double-submit pair an attacker's origin cannot read.
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
