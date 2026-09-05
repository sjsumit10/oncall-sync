"""The PagerDuty adapter: payload mapping, pagination, retries and auth errors."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.core.http import ProviderAuthError, ProviderError
from app.domain.types import AuthMode, Credentials
from app.providers.oncall.pagerduty.provider import PagerDutyProvider
from tests.pagerduty_fixtures import (
    API,
    oncall,
    oncalls_page,
    schedule,
    schedule_v3,
    schedules_page,
)

CREDS = Credentials(org_id=uuid.uuid4(), auth_mode=AuthMode.API_KEY, token="pd-key")
WINDOW_START = datetime(2026, 8, 24, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 7, tzinfo=UTC)


@respx.mock
async def test_api_key_uses_the_token_scheme() -> None:
    route = respx.get(f"{API}/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([]))
    )
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(200, json=schedules_page([])))
    await PagerDutyProvider().verify(CREDS)

    assert route.calls.last.request.headers["Authorization"] == "Token token=pd-key"
    assert "vnd.pagerduty+json;version=2" in route.calls.last.request.headers["Accept"]


@respx.mock
async def test_oauth_uses_the_bearer_scheme() -> None:
    route = respx.get(f"{API}/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([]))
    )
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(200, json=schedules_page([])))
    creds = Credentials(org_id=uuid.uuid4(), auth_mode=AuthMode.OAUTH, token="access-token")
    await PagerDutyProvider().verify(creds)

    assert route.calls.last.request.headers["Authorization"] == "Bearer access-token"


@respx.mock
async def test_list_schedules_follows_pagination() -> None:
    respx.get(f"{API}/schedules").mock(
        side_effect=[
            httpx.Response(200, json=schedules_page([schedule("P1", "Primary")], more=True)),
            httpx.Response(
                200, json=schedules_page([schedule("P2", "Secondary", "Europe/Berlin")])
            ),
        ]
    )
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(200, json=schedules_page([])))
    schedules = await PagerDutyProvider().list_schedules(CREDS)

    assert [s.external_id for s in schedules] == ["P1", "P2"]
    assert schedules[1].timezone == "Europe/Berlin"
    assert schedules[0].html_url == "https://acme.pagerduty.com/schedules/P1"


@respx.mock
async def test_list_schedules_merges_shift_based_schedules() -> None:
    respx.get(f"{API}/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([schedule("P1", "Classic")]))
    )
    respx.get(f"{API}/v3/schedules").mock(
        side_effect=[
            httpx.Response(
                200, json=schedules_page([schedule_v3("PV1", "Shift-based")], more=True)
            ),
            httpx.Response(200, json=schedules_page([schedule_v3("PV2", "Shift-based 2")])),
        ]
    )
    schedules = await PagerDutyProvider().list_schedules(CREDS)

    assert [s.external_id for s in schedules] == ["P1", "PV1", "PV2"]
    assert schedules[1].name == "Shift-based"
    assert schedules[1].timezone == "UTC"


@respx.mock
async def test_list_schedules_tolerates_v3_endpoint_being_unavailable() -> None:
    """Accounts without shift-based scheduling enabled don't have /v3/schedules."""
    respx.get(f"{API}/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([schedule("P1", "Classic")]))
    )
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(404, json={}))
    schedules = await PagerDutyProvider().list_schedules(CREDS)

    assert [s.external_id for s in schedules] == ["P1"]


@respx.mock
async def test_oncall_window_maps_to_spans() -> None:
    respx.get(f"{API}/oncalls").mock(
        return_value=httpx.Response(
            200,
            json=oncalls_page(
                [
                    oncall("PU2", "Bob", "bob@acme.dev", "2026-08-31T09:00:00Z", None, level=2),
                    oncall(
                        "PU1",
                        "Ada",
                        "ada@acme.dev",
                        "2026-08-24T09:00:00Z",
                        "2026-08-31T09:00:00Z",
                    ),
                ]
            ),
        )
    )
    spans = await PagerDutyProvider().get_oncall_window(CREDS, "PSCHED1", WINDOW_START, WINDOW_END)

    # Sorted by start, so the next handoff boundary is simply the next span.
    assert [s.user.name for s in spans] == ["Ada", "Bob"]
    assert spans[0].user.email == "ada@acme.dev"
    assert spans[0].end == datetime(2026, 8, 31, 9, tzinfo=UTC)
    assert spans[1].end is None  # open-ended shift
    assert spans[1].level == 2


@respx.mock
async def test_oncall_window_requests_inflated_users() -> None:
    """Emails are the join key to chat accounts, so users must come back inflated."""
    route = respx.get(f"{API}/oncalls").mock(
        return_value=httpx.Response(200, json=oncalls_page([]))
    )
    await PagerDutyProvider().get_oncall_window(CREDS, "PSCHED1", WINDOW_START, WINDOW_END)

    params = route.calls.last.request.url.params
    assert params["include[]"] == "users"
    assert params["schedule_ids[]"] == "PSCHED1"
    assert params["time_zone"] == "UTC"


def test_span_covers_the_instant_it_starts_but_not_the_instant_it_ends() -> None:
    from app.domain.types import OncallSpan, ProviderUser

    span = OncallSpan(
        user=ProviderUser("PU1", "Ada"),
        start=datetime(2026, 8, 24, 9, tzinfo=UTC),
        end=datetime(2026, 8, 31, 9, tzinfo=UTC),
    )
    # Half-open, so back-to-back shifts never both claim the handoff instant.
    assert span.covers(datetime(2026, 8, 24, 9, tzinfo=UTC))
    assert span.covers(datetime(2026, 8, 30, tzinfo=UTC))
    assert not span.covers(datetime(2026, 8, 31, 9, tzinfo=UTC))
    assert not span.covers(datetime(2026, 8, 20, tzinfo=UTC))


@respx.mock
async def test_rate_limit_is_retried_then_succeeds() -> None:
    route = respx.get(f"{API}/schedules").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=schedules_page([schedule("P1", "Primary")])),
        ]
    )
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(200, json=schedules_page([])))
    schedules = await PagerDutyProvider().list_schedules(CREDS)

    assert route.call_count == 2
    assert [s.external_id for s in schedules] == ["P1"]


@respx.mock
async def test_unauthorized_is_not_retried() -> None:
    """A bad credential cannot be fixed by trying again, and retrying burns quota."""
    route = respx.get(f"{API}/schedules").mock(return_value=httpx.Response(401, text="nope"))

    with pytest.raises(ProviderAuthError):
        await PagerDutyProvider().verify(CREDS)
    assert route.call_count == 1


@respx.mock
async def test_persistent_server_error_surfaces_after_retries() -> None:
    route = respx.get(f"{API}/schedules").mock(
        return_value=httpx.Response(500, headers={"Retry-After": "0"}, text="boom")
    )

    with pytest.raises(ProviderError):
        await PagerDutyProvider().verify(CREDS)
    assert route.call_count > 1
