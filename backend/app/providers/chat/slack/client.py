"""Slack Web API client.

Slack answers 200 with ``{"ok": false, "error": "..."}`` for application-level
failures, so errors are read from the body rather than the status line. The error
codes are part of the contract and several of them drive product behaviour, so
they are named here rather than buried in strings.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
from redis.asyncio import Redis

from app.core import metrics
from app.core.http import ProviderAuthError, ProviderError, RateLimiter, request

PROVIDER = "slack"
API_BASE = "https://slack.com/api"
PAGE_SIZE = 200
MAX_PAGES = 50

#: usergroups.* is Tier 2 (~20 requests/minute). Stay comfortably under it.
USERGROUP_RATE_LIMIT = 15
RATE_WINDOW_SECONDS = 60

#: The token is bad or gone. Not retryable — the workspace must be reinstalled.
AUTH_ERRORS = frozenset(
    {"invalid_auth", "not_authed", "token_revoked", "account_inactive", "token_expired"}
)
#: The token is valid but this workspace restricts who may manage user groups.
PERMISSION_DENIED = "permission_denied"
#: User groups are a Standard-and-above feature.
PLAN_UPGRADE_REQUIRED = "plan_upgrade_required"
#: Slack refuses to leave a user group with no members.
EMPTY_MEMBERSHIP_ERRORS = frozenset({"invalid_users", "no_users_provided"})


class SlackApiError(ProviderError):
    """A Slack call that returned ok:false."""

    def __init__(self, method: str, error: str, detail: str | None = None) -> None:
        super().__init__(f"Slack {method} failed: {error}{f' ({detail})' if detail else ''}")
        self.error = error
        self.method = method


class SlackClient:
    def __init__(
        self,
        token: str,
        *,
        org_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        redis: Redis | None = None,
    ) -> None:
        self._token = token
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        self._owns_client = client is None
        self._limiter = RateLimiter(
            redis=redis,
            key=f"ratelimit:slack:usergroups:{org_id or 'global'}",
            limit=USERGROUP_RATE_LIMIT,
            window_seconds=RATE_WINDOW_SECONDS,
            provider=PROVIDER,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def call(
        self, method: str, params: dict[str, Any] | None = None, *, write: bool = False
    ) -> dict[str, Any]:
        """Invoke a Web API method, raising on ok:false."""
        response = await request(
            self._client,
            "POST",
            f"{API_BASE}/{method}",
            # Only the Tier 2 user-group writes need the shared budget; reads are
            # cheap and throttling them would slow every picker in the UI.
            limiter=self._limiter if write else None,
            provider=PROVIDER,
            headers={"Authorization": f"Bearer {self._token}"},
            data={k: v for k, v in (params or {}).items() if v is not None},
        )
        payload: dict[str, Any] = response.json()
        if payload.get("ok"):
            return payload

        error = str(payload.get("error", "unknown_error"))
        # Slack answers 200 with ok:false, so these never reach the status-code
        # counter in the HTTP layer and have to be recorded here.
        metrics.PROVIDER_ERRORS.labels(provider=PROVIDER, code=error).inc()
        if error in AUTH_ERRORS:
            raise ProviderAuthError(f"Slack {method} rejected the token: {error}")
        raise SlackApiError(method, error, payload.get("needed"))

    async def paginate(
        self, method: str, key: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield items under ``key``, following Slack's cursor pagination."""
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page = await self.call(method, {**(params or {}), "limit": PAGE_SIZE, "cursor": cursor})
            for item in page.get(key, []):
                yield item
            cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                return
