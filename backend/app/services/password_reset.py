"""Short-lived password reset tokens, held in Redis.

Five minutes is deliberately tight: this is a bearer credential mailed in
plain text, and a short window limits how long an intercepted or leaked email
stays exploitable. Single-use like an invite token, but never persisted to
Postgres — Redis's own TTL is the entire expiry mechanism, so there is nothing
to clean up later and nothing for the token to prove once it has expired.
"""

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta

from redis.asyncio import Redis

from app.core.security import generate_token, hash_token

RESET_TTL = timedelta(minutes=5)
_KEY = "password_reset:{digest}"


@dataclass(slots=True)
class PasswordReset:
    user_id: str


async def issue(redis: Redis, *, user_id: uuid.UUID) -> str:
    token = generate_token()
    payload = PasswordReset(user_id=str(user_id))
    key = _KEY.format(digest=hash_token(token))
    await redis.set(key, json.dumps(asdict(payload)), ex=RESET_TTL)
    return token


async def consume(redis: Redis, token: str) -> PasswordReset | None:
    """Fetch and delete in one shot — a token may be redeemed exactly once."""
    key = _KEY.format(digest=hash_token(token))
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    return PasswordReset(**json.loads(raw)) if raw else None
