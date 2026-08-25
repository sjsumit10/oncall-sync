"""Metrics, the activity log and the health summary.

The handoff-lag histogram is the product's core SLI, so most of the care here is
about what must *not* be counted into it: a manual sync, a first sync and a drift
repair would each report a "lag" that says nothing about how quickly handoffs are
picked up.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from httpx import AsyncClient
from prometheus_client import REGISTRY
from pydantic import SecretStr

from app.config import get_settings
from app.db.models import RunTrigger
from tests.conftest import csrf
from tests.factories import connected_org, rule_payload
from tests.pagerduty_fixtures import API as PD_API
from tests.pagerduty_fixtures import oncall, oncalls_page
from tests.slack_fixtures import API as SLACK_API
from tests.slack_fixtures import err, ok, slack_user

RULES = "/api/v1/rules"
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def provider_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


def stamp(hours: float) -> str:
    return (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def metric(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels or None) or 0.0


def lag_count() -> float:
    return metric("oncall_handoff_lag_seconds_count")


def mock_slack(group_members: list[str]) -> dict[str, respx.Route]:
    return {
        "lookup": respx.post(f"{SLACK_API}/users.lookupByEmail").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=ok(
                    user=slack_user("U_ADA", "Ada", "ada@acme.dev")
                    if b"ada" in request.content
                    else slack_user("U_BOB", "Bob", "bob@acme.dev")
                ),
            )
        ),
        "list": respx.post(f"{SLACK_API}/usergroups.users.list").mock(
            return_value=httpx.Response(200, json=ok(users=group_members))
        ),
        "update": respx.post(f"{SLACK_API}/usergroups.users.update").mock(
            return_value=httpx.Response(200, json=ok())
        ),
        "post": respx.post(f"{SLACK_API}/chat.postMessage").mock(
            return_value=httpx.Response(200, json=ok(channel="C_OPS", ts="1.1"))
        ),
    }


def mock_oncall(user: tuple[str, str, str], start: float, end: float) -> respx.Route:
    external_id, name, email = user
    return respx.get(f"{PD_API}/oncalls").mock(
        return_value=httpx.Response(
            200, json=oncalls_page([oncall(external_id, name, email, stamp(start), stamp(end))])
        )
    )


async def make_rule(client: AsyncClient, **overrides: object) -> dict:
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids, **overrides), headers=csrf(client))
    assert created.status_code == 201, created.text
    return created.json()


async def sync(client: AsyncClient, rule_id: str) -> dict:
    response = await client.post(f"{RULES}/{rule_id}/sync", headers=csrf(client))
    assert response.status_code == 200, response.text
    return response.json()


async def scheduled_run(client: AsyncClient, rule_id: str, org_id: str) -> str:
    """Drive a run the way the scheduler does, not via the manual endpoint."""
    from app.worker.tasks import reconcile_rule

    return await reconcile_rule({}, rule_id, org_id, RunTrigger.SCHEDULED.value)


@respx.mock
async def test_run_counters_record_outcome_and_trigger(client: AsyncClient) -> None:
    rule = await make_rule(client)
    before = metric("oncall_sync_runs_total", status="success", trigger="manual")
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])

    await sync(client, rule["id"])

    assert metric("oncall_sync_runs_total", status="success", trigger="manual") == before + 1


@respx.mock
async def test_group_writes_distinguish_handoffs_from_drift_repairs(
    client: AsyncClient,
) -> None:
    rule = await make_rule(client)
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])
    handoffs = metric("oncall_group_writes_total", reason="handoff")
    await sync(client, rule["id"])
    assert metric("oncall_group_writes_total", reason="handoff") == handoffs + 1

    # Same person, group tampered with: a repair, not a handoff.
    respx.reset()
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack(["U_INTRUDER"])
    repairs = metric("oncall_group_writes_total", reason="drift_repair")
    await sync(client, rule["id"])

    assert metric("oncall_group_writes_total", reason="drift_repair") == repairs + 1
    assert metric("oncall_group_writes_total", reason="handoff") == handoffs + 1


@respx.mock
async def test_a_manual_sync_is_never_counted_as_handoff_lag(client: AsyncClient) -> None:
    """Someone pressing "Sync now" says nothing about scheduling latency."""
    rule = await make_rule(client)
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])
    await sync(client, rule["id"])

    respx.reset()
    mock_oncall(("PU2", "Bob", "bob@acme.dev"), -1, 8)
    mock_slack(["U_ADA"])
    before = lag_count()

    await sync(client, rule["id"])

    assert lag_count() == before, "manual syncs must not enter the SLI"


@respx.mock
async def test_a_first_sync_is_never_counted_as_handoff_lag(client: AsyncClient) -> None:
    """There is no previous state, so the shift start is not a handoff we missed."""
    rule = await make_rule(client)
    org_id = (await client.get("/api/v1/auth/me")).json()["organization"]["id"]
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -6, 6)
    mock_slack([])
    before = lag_count()

    assert await scheduled_run(client, rule["id"], org_id) == "success"

    assert lag_count() == before


@respx.mock
async def test_a_drift_repair_is_never_counted_as_handoff_lag(client: AsyncClient) -> None:
    rule = await make_rule(client)
    org_id = (await client.get("/api/v1/auth/me")).json()["organization"]["id"]
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -6, 6)
    mock_slack([])
    await scheduled_run(client, rule["id"], org_id)

    respx.reset()
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -6, 6)
    mock_slack(["U_INTRUDER"])
    before = lag_count()

    await scheduled_run(client, rule["id"], org_id)

    assert lag_count() == before, "the people did not change; nothing was late"


@respx.mock
async def test_a_real_scheduled_handoff_is_measured(client: AsyncClient) -> None:
    rule = await make_rule(client)
    org_id = (await client.get("/api/v1/auth/me")).json()["organization"]["id"]
    # Ada's shift must cover now, so there is a previous state to hand off from.
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -6, 2)
    mock_slack([])
    await scheduled_run(client, rule["id"], org_id)

    # Bob's shift started an hour ago; we are only catching up now.
    respx.reset()
    mock_oncall(("PU2", "Bob", "bob@acme.dev"), -1, 8)
    mock_slack(["U_ADA"])
    before = lag_count()
    before_sum = metric("oncall_handoff_lag_seconds_sum")

    await scheduled_run(client, rule["id"], org_id)

    assert lag_count() == before + 1
    observed = metric("oncall_handoff_lag_seconds_sum") - before_sum
    assert 3500 < observed < 3700, "should measure from the shift start, not the run start"


@respx.mock
async def test_slack_body_level_errors_are_counted(client: AsyncClient) -> None:
    """Slack answers 200 with ok:false, so status codes alone would miss these."""
    rule = await make_rule(client)
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])
    respx.post(f"{SLACK_API}/usergroups.users.update").mock(
        return_value=httpx.Response(200, json=err("permission_denied"))
    )
    before = metric("oncall_provider_api_errors_total", provider="slack", code="permission_denied")

    await sync(client, rule["id"])

    # Two, not one: the bot token is denied, then the user-token fallback is too.
    # Both are real failed calls and both should be visible.
    assert (
        metric("oncall_provider_api_errors_total", provider="slack", code="permission_denied")
        == before + 2
    )


@respx.mock
async def test_pagerduty_status_errors_are_counted(client: AsyncClient) -> None:
    rule = await make_rule(client)
    respx.get(f"{PD_API}/oncalls").mock(return_value=httpx.Response(401, text="nope"))
    before = metric("oncall_provider_api_errors_total", provider="pagerduty", code="401")

    await sync(client, rule["id"])

    assert (
        metric("oncall_provider_api_errors_total", provider="pagerduty", code="401") == before + 1
    )


@respx.mock
async def test_unmapped_people_are_counted(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall(("PU9", "Contractor", "carol@vendor.dev"), -1, 6)
    respx.post(f"{SLACK_API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json=err("users_not_found"))
    )
    mock_slack([])
    respx.post(f"{SLACK_API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json=err("users_not_found"))
    )
    before = metric("oncall_unmapped_identities_total")

    await sync(client, rule["id"])

    assert metric("oncall_unmapped_identities_total") > before


@respx.mock
async def test_metrics_endpoint_reports_rule_gauges(client: AsyncClient) -> None:
    await make_rule(client)
    body = (await client.get("/metrics")).text

    assert 'oncall_rules{status="pending"}' in body
    assert "oncall_handoff_lag_seconds_bucket" in body
    # Gauges are read at scrape time, so every status is present even at zero.
    assert 'oncall_rules{status="failing"} 0.0' in body


@respx.mock
async def test_activity_log_reads_without_opening_the_rule(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])
    await sync(client, rule["id"])

    activity = (await client.get("/api/v1/activity")).json()

    assert len(activity) == 1
    assert activity[0]["rule_name"] == "DevOps on-call"
    assert activity[0]["status"] == "success"
    assert "Updated group membership" in activity[0]["actions"]


@respx.mock
async def test_activity_can_be_filtered_by_status(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])
    await sync(client, rule["id"])

    respx.reset()
    respx.get(f"{PD_API}/oncalls").mock(return_value=httpx.Response(401, text="nope"))
    await sync(client, rule["id"])

    failed = (await client.get("/api/v1/activity?status=failed")).json()
    assert [run["status"] for run in failed] == ["failed"]


@respx.mock
async def test_activity_is_scoped_to_the_org(client: AsyncClient, invitee: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])
    await sync(client, rule["id"])
    respx.reset()
    await connected_org(invitee, org="Globex", email="owner@globex.dev")

    assert (await invitee.get("/api/v1/activity")).json() == []
    assert len((await client.get("/api/v1/activity")).json()) == 1


@respx.mock
async def test_overview_summarises_rule_health(client: AsyncClient) -> None:
    rule = await make_rule(client)
    before = (await client.get("/api/v1/overview")).json()
    assert before["rules_total"] == 1
    assert before["rules_by_status"] == {"pending": 1}
    assert before["last_handoff_at"] is None

    mock_oncall(("PU1", "Ada", "ada@acme.dev"), -2, 6)
    mock_slack([])
    await sync(client, rule["id"])

    after = (await client.get("/api/v1/overview")).json()
    assert after["rules_by_status"] == {"healthy": 1}
    assert after["last_run_at"] is not None
    # First sync had no previous membership, so it is not yet a handoff.
    assert after["last_handoff_at"] is None


@respx.mock
async def test_overview_counts_connections_needing_attention(client: AsyncClient) -> None:
    rule = await make_rule(client)
    respx.get(f"{PD_API}/oncalls").mock(return_value=httpx.Response(401, text="nope"))
    await sync(client, rule["id"])

    overview = (await client.get("/api/v1/overview")).json()
    assert overview["connections_needing_attention"] == 1


def posted_text(route: respx.Route) -> str:
    return parse_qs(route.calls.last.request.content.decode())["text"][0]
