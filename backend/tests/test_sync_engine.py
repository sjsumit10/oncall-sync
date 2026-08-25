"""The reconcile loop.

The distinction these tests exist to protect: membership is rewritten whenever
Slack disagrees with the rule, but a message is posted only when the on-call
people actually changed. Repairing a hand-edited group must never announce a
handoff that did not happen.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import get_settings
from tests.conftest import csrf
from tests.factories import connected_org, rule_payload
from tests.pagerduty_fixtures import API as PD_API
from tests.pagerduty_fixtures import oncall, oncalls_page
from tests.slack_fixtures import API as SLACK_API
from tests.slack_fixtures import err, ok, slack_user

RULES = "/api/v1/rules"
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def provider_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


def stamp(hours: int) -> str:
    return (NOW.replace(microsecond=0) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def mock_oncall(entries: list[dict]) -> respx.Route:
    return respx.get(f"{PD_API}/oncalls").mock(
        return_value=httpx.Response(200, json=oncalls_page(entries))
    )


def mock_lookup(mapping: dict[str, dict]) -> respx.Route:
    def handler(request: httpx.Request) -> httpx.Response:
        email = dict(httpx.QueryParams(request.content.decode()))["email"]
        user = mapping.get(email)
        return httpx.Response(200, json=ok(user=user) if user else err("users_not_found"))

    return respx.post(f"{SLACK_API}/users.lookupByEmail").mock(side_effect=handler)


def mock_group(members: list[str]) -> respx.Route:
    return respx.post(f"{SLACK_API}/usergroups.users.list").mock(
        return_value=httpx.Response(200, json=ok(users=members))
    )


def mock_update() -> respx.Route:
    return respx.post(f"{SLACK_API}/usergroups.users.update").mock(
        return_value=httpx.Response(200, json=ok())
    )


def posted_text(route: respx.Route) -> str:
    """The message body Slack received, form-decoded."""
    return parse_qs(route.calls.last.request.content.decode())["text"][0]


def mock_post() -> respx.Route:
    return respx.post(f"{SLACK_API}/chat.postMessage").mock(
        return_value=httpx.Response(200, json=ok(channel="C_OPS", ts="1.1"))
    )


ADA = slack_user("U_ADA", "Ada", "ada@acme.dev")
BOB = slack_user("U_BOB", "Bob", "bob@acme.dev")
DIRECTORY = {"ada@acme.dev": ADA, "bob@acme.dev": BOB}


async def make_rule(client: AsyncClient, **overrides: object) -> dict:
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids, **overrides), headers=csrf(client))
    assert created.status_code == 201, created.text
    return created.json()


async def sync(client: AsyncClient, rule_id: str) -> dict:
    response = await client.post(f"{RULES}/{rule_id}/sync", headers=csrf(client))
    assert response.status_code == 200, response.text
    return response.json()


@respx.mock
async def test_first_sync_writes_membership_and_announces(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group(["U_STALE"])
    update, post = mock_update(), mock_post()

    run = await sync(client, rule["id"])

    assert run["status"] == "success"
    assert run["new_members"] == ["U_ADA"]
    assert update.call_count == 1
    assert "users=U_ADA" in update.calls.last.request.content.decode()
    assert post.call_count == 1


@respx.mock
async def test_repairing_manual_drift_does_not_announce(client: AsyncClient) -> None:
    """Someone hand-edited the group. Fix it, but do not fake a handoff."""
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group(["U_STALE"])
    mock_update()
    post = mock_post()
    await sync(client, rule["id"])
    assert post.call_count == 1

    # Same person on call, but the group has been tampered with.
    respx.reset()
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group(["U_INTRUDER"])
    update, post = mock_update(), mock_post()

    run = await sync(client, rule["id"])

    assert update.call_count == 1, "membership must be repaired"
    assert post.call_count == 0, "a repair is not a handoff"
    assert "Repaired manual drift" in run["actions"]


@respx.mock
async def test_a_real_handoff_announces_once(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group([])
    mock_update()
    mock_post()
    await sync(client, rule["id"])

    respx.reset()
    mock_oncall([oncall("PU2", "Bob", "bob@acme.dev", stamp(-1), stamp(12))])
    mock_lookup(DIRECTORY)
    mock_group(["U_ADA"])
    update, post = mock_update(), mock_post()

    run = await sync(client, rule["id"])

    assert run["previous_members"] == ["U_ADA"]
    assert run["new_members"] == ["U_BOB"]
    assert update.call_count == 1
    assert post.call_count == 1
    body = posted_text(post)
    assert "U_BOB" in body
    assert "U_ADA" in body, "the outgoing person should be named"


@respx.mock
async def test_an_unchanged_run_writes_nothing(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group([])
    mock_update()
    mock_post()
    await sync(client, rule["id"])

    respx.reset()
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group(["U_ADA"])
    update, post = mock_update(), mock_post()

    run = await sync(client, rule["id"])

    assert update.call_count == 0
    assert post.call_count == 0
    assert "Group already correct" in run["actions"]


@respx.mock
async def test_quiet_mode_updates_without_posting(client: AsyncClient) -> None:
    rule = await make_rule(client, notify_on_change=False, notify_channel_external_id=None)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group([])
    update, post = mock_update(), mock_post()

    await sync(client, rule["id"])

    assert update.call_count == 1
    assert post.call_count == 0


@respx.mock
async def test_nobody_resolves_leaves_the_group_untouched(client: AsyncClient) -> None:
    """The single most important safety property: never empty a live handle."""
    rule = await make_rule(client)
    mock_oncall([oncall("PU9", "Contractor", "carol@vendor.dev", stamp(-1), stamp(6))])
    mock_lookup({})
    mock_group(["U_ADA"])
    update, post = mock_update(), mock_post()

    run = await sync(client, rule["id"])

    assert run["status"] == "degraded"
    assert update.call_count == 0, "the handle must be left exactly as it was"
    assert run["new_members"] is None
    # The channel is told once, on the transition into degraded.
    assert post.call_count == 1
    assert "could not update" in posted_text(post)

    rule_after = (await client.get(f"{RULES}/{rule['id']}")).json()
    assert rule_after["status"] == "degraded"


@respx.mock
async def test_the_degraded_alert_is_not_repeated_every_interval(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU9", "Contractor", "carol@vendor.dev", stamp(-1), stamp(6))])
    mock_lookup({})
    mock_group(["U_ADA"])
    mock_update()
    post = mock_post()

    await sync(client, rule["id"])
    assert post.call_count == 1
    await sync(client, rule["id"])
    assert post.call_count == 1, "still degraded is not news"


@respx.mock
async def test_nobody_on_call_uses_the_fallback(client: AsyncClient) -> None:
    rule = await make_rule(client, fallback_chat_user_id="U_LEAD")
    mock_oncall([])
    mock_group(["U_ADA"])
    update = mock_update()
    mock_post()

    run = await sync(client, rule["id"])

    assert update.call_count == 1
    assert "users=U_LEAD" in update.calls.last.request.content.decode()
    assert run["new_members"] == ["U_LEAD"]


@respx.mock
async def test_a_paused_rule_is_skipped_and_unscheduled(client: AsyncClient) -> None:
    rule = await make_rule(client, enabled=False)
    oncalls = mock_oncall([])
    update = mock_update()

    run = await sync(client, rule["id"])

    assert run["status"] == "skipped"
    assert oncalls.call_count == 0, "a paused rule should not even query the provider"
    assert update.call_count == 0


@respx.mock
async def test_provider_failure_is_recorded_and_backed_off(client: AsyncClient) -> None:
    rule = await make_rule(client)
    respx.get(f"{PD_API}/oncalls").mock(
        return_value=httpx.Response(500, headers={"Retry-After": "0"}, text="boom")
    )
    update = mock_update()

    run = await sync(client, rule["id"])

    assert run["status"] == "failed"
    assert run["error"]
    assert update.call_count == 0

    after = (await client.get(f"{RULES}/{rule['id']}")).json()
    assert after["consecutive_failures"] == 1
    assert after["last_error"]


@respx.mock
async def test_a_revoked_pagerduty_credential_flags_the_connection(
    client: AsyncClient,
) -> None:
    rule = await make_rule(client)
    respx.get(f"{PD_API}/oncalls").mock(return_value=httpx.Response(401, text="nope"))

    run = await sync(client, rule["id"])
    assert run["status"] == "failed"

    connections = (await client.get("/api/v1/oncall/connections")).json()
    assert connections[0]["status"] == "needs_reauth"


@respx.mock
async def test_a_connection_needing_reauth_short_circuits(client: AsyncClient) -> None:
    """Retrying a dead token burns rate limit and hides the real fix."""
    rule = await make_rule(client)
    respx.get(f"{PD_API}/oncalls").mock(return_value=httpx.Response(401, text="nope"))
    await sync(client, rule["id"])

    respx.reset()
    oncalls = mock_oncall([])
    run = await sync(client, rule["id"])

    assert run["status"] == "skipped"
    assert oncalls.call_count == 0


@respx.mock
async def test_a_locked_down_workspace_degrades_rather_than_failing(
    client: AsyncClient,
) -> None:
    """permission_denied on both tokens is a configuration problem, not a fault."""
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group([])
    respx.post(f"{SLACK_API}/usergroups.users.update").mock(
        return_value=httpx.Response(200, json=err("permission_denied"))
    )

    run = await sync(client, rule["id"])

    assert run["status"] == "degraded"
    assert any("Workspace settings" in problem for problem in run["problems"])
    after = (await client.get(f"{RULES}/{rule['id']}")).json()
    assert after["consecutive_failures"] == 0, "not a transient failure"


@respx.mock
async def test_runs_are_listed_newest_first(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6))])
    mock_lookup(DIRECTORY)
    mock_group([])
    mock_update()
    mock_post()
    await sync(client, rule["id"])
    await sync(client, rule["id"])

    runs = (await client.get(f"{RULES}/{rule['id']}/runs")).json()
    assert len(runs) == 2
    assert runs[0]["started_at"] >= runs[1]["started_at"]
    assert {run["trigger"] for run in runs} == {"manual"}


@respx.mock
async def test_another_org_cannot_sync_or_read_runs(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    rule = await make_rule(client)
    respx.reset()
    await connected_org(invitee, email="owner@globex.dev")

    assert (
        await invitee.post(f"{RULES}/{rule['id']}/sync", headers=csrf(invitee))
    ).status_code == 404
    assert (await invitee.get(f"{RULES}/{rule['id']}/runs")).status_code == 404
