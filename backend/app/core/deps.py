"""Request dependencies: authentication, CSRF, RBAC and org scoping."""

import secrets
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Unauthorized
from app.core.redis import get_redis
from app.core.sessions import CSRF_HEADER, SESSION_COOKIE, read_session
from app.db.models import User, UserRole
from app.db.session import bind_org, get_session

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

DbSession = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]


async def get_current_user(request: Request, db: DbSession, redis: RedisClient) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized

    session_data = await read_session(redis, token)
    if session_data is None:
        raise Unauthorized("Session expired")

    user = await db.scalar(select(User).where(User.id == uuid.UUID(session_data.user_id)))
    if user is None or not user.is_active:
        raise Unauthorized("Account is no longer active")

    await bind_org(db, user.org_id)

    request.state.csrf_token = session_data.csrf_token
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_csrf(request: Request, redis: RedisClient) -> None:
    """Double-submit CSRF check on state-changing requests.

    Only enforced when a session cookie is present, so signup and login — which
    have no session yet — are naturally exempt.
    """
    if request.method in SAFE_METHODS:
        return

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return

    session_data = await read_session(redis, token)
    if session_data is None:
        return

    supplied = request.headers.get(CSRF_HEADER, "")
    if not secrets.compare_digest(supplied, session_data.csrf_token):
        raise Forbidden("Missing or invalid CSRF token")


def require_role(*allowed: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory gating an endpoint on the caller's role."""

    async def dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise Forbidden(f"Requires one of: {', '.join(sorted(r.value for r in allowed))}")
        return user

    return dependency
