"""Fixed-window counters in Redis.

Used for login throttling now; the provider API token buckets in M5 build on the
same client.
"""

from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int


async def hit(redis: Redis, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
    """Count one attempt against ``key`` and report whether it is allowed."""
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    count, ttl = await pipe.execute()

    if ttl < 0:
        await redis.expire(key, window_seconds)
        ttl = window_seconds

    return RateLimitResult(
        allowed=count <= limit,
        remaining=max(0, limit - count),
        retry_after_seconds=ttl,
    )


async def reset(redis: Redis, key: str) -> None:
    await redis.delete(key)
