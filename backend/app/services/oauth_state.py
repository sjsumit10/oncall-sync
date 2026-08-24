"""Short-lived OAuth state, held in Redis.

The state parameter is the CSRF defence for the redirect leg: it is unguessable,
single-use, and bound to the session that started the flow, so a callback
delivered to a different browser is rejected. The PKCE verifier rides along here
so it never reaches the user agent.
"""

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta

from redis.asyncio import Redis

from app.core.security import generate_token, hash_token

STATE_TTL = timedelta(minutes=10)
_KEY = "oauth_state:{digest}"


@dataclass(slots=True)
class OAuthState:
    org_id: str
    user_id: str
    kind: str
    code_verifier: str
    redirect_uri: str


async def issue(redis: Redis, *, org_id: uuid.UUID, user_id: uuid.UUID, **rest: str) -> str:
    state = generate_token()
    payload = OAuthState(org_id=str(org_id), user_id=str(user_id), **rest)
    await redis.set(
        _KEY.format(digest=hash_token(state)), json.dumps(asdict(payload)), ex=STATE_TTL
    )
    return state


async def consume(redis: Redis, state: str) -> OAuthState | None:
    """Fetch and delete in one shot — a state may be redeemed exactly once."""
    key = _KEY.format(digest=hash_token(state))
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    return OAuthState(**json.loads(raw)) if raw else None
