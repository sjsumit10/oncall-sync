"""Server-side sessions in Redis.

The cookie carries an opaque id only; all session state lives server-side so a
logout, a role change or a password reset takes effect immediately rather than
waiting for a self-describing token to expire.
"""

import json
import uuid
from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import cast

from redis.asyncio import Redis

from app.core.security import generate_token, hash_token

SESSION_COOKIE = "oncall_session"
CSRF_COOKIE = "oncall_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL = timedelta(days=1)

_SESSION_KEY = "session:{sid_hash}"
_USER_SESSIONS_KEY = "user_sessions:{user_id}"


@dataclass(slots=True)
class SessionData:
    user_id: str
    org_id: str
    csrf_token: str


def _session_key(token: str) -> str:
    # The raw cookie value is never a Redis key: a leaked key listing would
    # otherwise hand over every live session.
    return _SESSION_KEY.format(sid_hash=hash_token(token))


async def create_session(redis: Redis, user_id: uuid.UUID, org_id: uuid.UUID) -> tuple[str, str]:
    """Return ``(session_token, csrf_token)``."""
    token = generate_token()
    data = SessionData(user_id=str(user_id), org_id=str(org_id), csrf_token=generate_token())

    pipe = redis.pipeline()
    pipe.set(_session_key(token), json.dumps(asdict(data)), ex=SESSION_TTL)
    pipe.sadd(_USER_SESSIONS_KEY.format(user_id=user_id), hash_token(token))
    pipe.expire(_USER_SESSIONS_KEY.format(user_id=user_id), SESSION_TTL)
    await pipe.execute()

    return token, data.csrf_token


async def read_session(redis: Redis, token: str) -> SessionData | None:
    raw = await redis.get(_session_key(token))
    if raw is None:
        return None
    # Sliding expiry: an active user is not logged out mid-session.
    await redis.expire(_session_key(token), SESSION_TTL)
    return SessionData(**json.loads(raw))


async def delete_session(redis: Redis, token: str) -> None:
    raw = await redis.get(_session_key(token))
    await redis.delete(_session_key(token))
    if raw is not None:
        data = SessionData(**json.loads(raw))
        await cast(
            Awaitable[int],
            redis.srem(_USER_SESSIONS_KEY.format(user_id=data.user_id), hash_token(token)),
        )


async def delete_user_sessions(redis: Redis, user_id: uuid.UUID) -> None:
    """Revoke every session for a user — used when they are removed or deactivated."""
    key = _USER_SESSIONS_KEY.format(user_id=user_id)
    hashes = await cast(Awaitable[set[str]], redis.smembers(key))
    if hashes:
        await redis.delete(*(_SESSION_KEY.format(sid_hash=h) for h in hashes))
    await redis.delete(key)
