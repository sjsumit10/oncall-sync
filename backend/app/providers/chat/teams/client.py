"""Microsoft Graph API client.

Unlike Slack, Graph answers with real HTTP status codes — a 401/403 is already
turned into ``ProviderAuthError`` and any other 4xx/5xx into ``ProviderError``
by the shared ``request()`` helper, retries and backoff included. There is no
Slack-style "200 with ok:false" body to hand-inspect, so this client stays
thin: build the URL and headers, let ``request()`` do the rest.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.http import request

API_BASE = "https://graph.microsoft.com/v1.0"
PAGE_SIZE = 50
MAX_PAGES = 50
PROVIDER = "teams"


class GraphClient:
    def __init__(self, access_token: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._token = access_token
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def call(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a Graph endpoint. ``path_or_url`` may be a path or a full
        ``@odata.nextLink`` URL — both are accepted so pagination can pass the
        link straight through without re-deriving query params."""
        url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}{path_or_url}"
        response = await request(
            self._client,
            method,
            url,
            provider=PROVIDER,
            headers=self._headers,
            params=params,
            json=json,
        )
        if response.status_code == 204 or not response.content:
            return {}
        payload: dict[str, Any] = response.json()
        return payload

    async def paginate(
        self, path: str, key: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield items under ``key``, following Graph's @odata.nextLink cursor."""
        next_url: str | None = path
        next_params: dict[str, Any] | None = {**(params or {}), "$top": PAGE_SIZE}
        for _ in range(MAX_PAGES):
            if next_url is None:
                return
            page = await self.call("GET", next_url, params=next_params)
            for item in page.get(key, []):
                yield item
            next_url = page.get("@odata.nextLink")
            next_params = None
