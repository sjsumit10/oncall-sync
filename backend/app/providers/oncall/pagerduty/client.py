"""PagerDuty REST API client.

Handles auth headers, cursor-free offset pagination and the account-wide rate
limit. Knows nothing about sync rules or the database.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
from redis.asyncio import Redis

from app.core.http import RateLimiter, request
from app.domain.types import AuthMode, Credentials

PROVIDER = "pagerduty"
API_BASE = "https://api.pagerduty.com"
ACCEPT = "application/vnd.pagerduty+json;version=2"
PAGE_SIZE = 100
#: PagerDuty allows ~900 REST requests per minute per account; stay under it.
RATE_LIMIT = 700
RATE_WINDOW_SECONDS = 60
#: Guards against a pagination bug turning into an unbounded loop.
MAX_PAGES = 50


class PagerDutyClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        client: httpx.AsyncClient | None = None,
        redis: Redis | None = None,
    ) -> None:
        self._credentials = credentials
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        self._owns_client = client is None
        # Scoped per organization: one noisy tenant must not exhaust another's budget.
        self._limiter = RateLimiter(
            redis=redis,
            key=f"ratelimit:pagerduty:{credentials.org_id}",
            limit=RATE_LIMIT,
            window_seconds=RATE_WINDOW_SECONDS,
            provider=PROVIDER,
        )

    async def __aenter__(self) -> "PagerDutyClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _headers(self) -> dict[str, str]:
        token = self._credentials.token
        authorization = (
            f"Token token={token}"
            if self._credentials.auth_mode is AuthMode.API_KEY
            else f"Bearer {token}"
        )
        return {"Authorization": authorization, "Accept": ACCEPT}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await request(
            self._client,
            "GET",
            f"{API_BASE}{path}",
            limiter=self._limiter,
            provider=PROVIDER,
            headers=self._headers,
            params=params,
        )
        payload: dict[str, Any] = response.json()
        return payload

    async def paginate(
        self, path: str, key: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every item under ``key``, following PagerDuty's offset paging."""
        offset = 0
        for _ in range(MAX_PAGES):
            page = await self.get(path, {**(params or {}), "limit": PAGE_SIZE, "offset": offset})
            items: list[dict[str, Any]] = page.get(key, [])
            for item in items:
                yield item
            if not page.get("more") or not items:
                return
            offset += len(items)
