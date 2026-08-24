"""Shared Redis client."""

from redis.asyncio import Redis, from_url

from app.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        # redis.asyncio.from_url is untyped upstream.
        _client = from_url(  # type: ignore[no-untyped-call]
            str(get_settings().redis_url), decode_responses=True
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
