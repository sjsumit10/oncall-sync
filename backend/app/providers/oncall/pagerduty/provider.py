"""PagerDuty adapter for the OncallProvider interface."""

from datetime import datetime
from typing import Any

import httpx
from redis.asyncio import Redis

from app.domain.types import (
    AuthMode,
    Credentials,
    OncallSpan,
    ProviderHealth,
    ProviderUser,
    ScheduleRef,
)
from app.providers.oncall.pagerduty.client import PagerDutyClient


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # PagerDuty emits RFC 3339 with a literal Z, which fromisoformat rejects
    # before 3.11 and accepts after; normalize regardless.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_user(payload: dict[str, Any]) -> ProviderUser:
    return ProviderUser(
        external_id=payload["id"],
        name=payload.get("name") or payload.get("summary") or payload["id"],
        # Only present when the caller asked for the user objects to be inflated.
        email=payload.get("email"),
    )


class PagerDutyProvider:
    kind: str = "pagerduty"
    display_name: str = "PagerDuty"
    # Annotated widely on purpose: the protocol declares tuple[AuthMode, ...], and
    # an inferred fixed-length tuple is not compatible with it.
    auth_modes: tuple[AuthMode, ...] = (AuthMode.OAUTH, AuthMode.API_KEY)

    def __init__(
        self, *, client: httpx.AsyncClient | None = None, redis: Redis | None = None
    ) -> None:
        # Injected in tests; production builds a client per call.
        self._client = client
        self._redis = redis

    def _api(self, credentials: Credentials) -> PagerDutyClient:
        return PagerDutyClient(credentials, client=self._client, redis=self._redis)

    async def verify(self, credentials: Credentials) -> ProviderHealth:
        """Round-trip the smallest call that needs the scopes we actually use."""
        api = self._api(credentials)
        try:
            payload = await api.get("/schedules", {"limit": 1})
        finally:
            await api.aclose()

        total = payload.get("total")
        detail = "Connected" if total is None else f"Connected · {total} schedules visible"
        return ProviderHealth(ok=True, detail=detail)

    async def list_schedules(self, credentials: Credentials) -> list[ScheduleRef]:
        api = self._api(credentials)
        try:
            return [
                ScheduleRef(
                    external_id=item["id"],
                    name=item.get("name") or item.get("summary") or item["id"],
                    timezone=item.get("time_zone") or "UTC",
                    description=item.get("description"),
                    html_url=item.get("html_url"),
                )
                async for item in api.paginate("/schedules", "schedules")
            ]
        finally:
            await api.aclose()

    async def get_oncall_window(
        self, credentials: Credentials, schedule_id: str, since: datetime, until: datetime
    ) -> list[OncallSpan]:
        """Every shift overlapping the window.

        /oncalls already accounts for overrides, so an override created minutes
        ago shows up here without special handling. include[]=users inflates the
        user reference into a full object carrying the email — the join key for
        matching PagerDuty people to chat accounts — which saves a lookup per
        person per reconcile.
        """
        api = self._api(credentials)
        params = {
            "schedule_ids[]": schedule_id,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "time_zone": "UTC",
            "include[]": "users",
        }
        try:
            spans = [
                OncallSpan(
                    user=_to_user(item["user"]),
                    start=start,
                    end=_parse_time(item.get("end")),
                    level=int(item.get("escalation_level") or 1),
                )
                async for item in api.paginate("/oncalls", "oncalls", params)
                if item.get("user") and (start := _parse_time(item.get("start"))) is not None
            ]
        finally:
            await api.aclose()

        return sorted(spans, key=lambda span: (span.start, span.level))

    async def list_users(self, credentials: Credentials) -> list[ProviderUser]:
        api = self._api(credentials)
        try:
            return [_to_user(item) async for item in api.paginate("/users", "users")]
        finally:
            await api.aclose()
