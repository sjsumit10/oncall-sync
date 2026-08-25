"""Outbound HTTP with retries, backoff and rate limiting.

Shared by every provider adapter so that retry policy, 429 handling and rate
limiting are decided once rather than per vendor.
"""

import asyncio
import random
from dataclasses import dataclass

import httpx
import structlog
from redis.asyncio import Redis

from app.core import metrics

log = structlog.get_logger(__name__)

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 30.0


class ProviderAuthError(RuntimeError):
    """Credentials were rejected. Not retryable — the user must reconnect."""


class ProviderError(RuntimeError):
    """The provider failed in a way retrying did not fix."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class RateLimiter:
    """Fixed-window limiter shared across processes via Redis.

    Waits for the window to roll rather than failing, because a delayed on-call
    sync is recoverable and a dropped one is not.
    """

    redis: Redis | None
    key: str
    limit: int
    window_seconds: int
    provider: str = "unknown"

    async def acquire(self) -> None:
        if self.redis is None:
            return
        for _ in range(3):
            count = await self.redis.incr(self.key)
            if count == 1:
                await self.redis.expire(self.key, self.window_seconds)
            if count <= self.limit:
                return
            ttl = await self.redis.ttl(self.key)
            wait = ttl if ttl and ttl > 0 else self.window_seconds
            metrics.RATE_LIMIT_HITS.labels(provider=self.provider).inc()
            log.warning("ratelimit.wait", key=self.key, seconds=wait)
            await asyncio.sleep(min(wait, self.window_seconds))


def _retry_after(response: httpx.Response, attempt: int) -> float:
    """Honour Retry-After when present, else exponential backoff with jitter."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt + random.uniform(0, 0.5), MAX_BACKOFF_SECONDS)  # noqa: S311


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    provider: str = "unknown",
    **kwargs: object,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(attempts):
        if limiter is not None:
            await limiter.acquire()

        try:
            response = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            metrics.PROVIDER_ERRORS.labels(provider=provider, code="transport").inc()
            if attempt == attempts - 1:
                break
            await asyncio.sleep(min(2.0**attempt, MAX_BACKOFF_SECONDS))
            continue

        # 401/403 mean the credential is wrong or under-scoped. Retrying cannot
        # help and would just burn the provider's rate limit.
        if response.status_code in (401, 403):
            metrics.PROVIDER_ERRORS.labels(provider=provider, code=str(response.status_code)).inc()
            raise ProviderAuthError(
                f"{method} {url} rejected with {response.status_code}: {response.text[:200]}"
            )

        if response.status_code in RETRY_STATUS and attempt < attempts - 1:
            if response.status_code == 429:
                metrics.RATE_LIMIT_HITS.labels(provider=provider).inc()
            delay = _retry_after(response, attempt)
            log.warning(
                "provider.retry", url=url, status=response.status_code, delay=delay, attempt=attempt
            )
            await asyncio.sleep(delay)
            continue

        if response.status_code >= 400:
            metrics.PROVIDER_ERRORS.labels(provider=provider, code=str(response.status_code)).inc()
            raise ProviderError(
                f"{method} {url} failed with {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )
        return response

    raise ProviderError(f"{method} {url} failed after {attempts} attempts: {last_error}")
