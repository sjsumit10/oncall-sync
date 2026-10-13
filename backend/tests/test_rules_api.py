"""Sync rule CRUD and validation."""

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import get_settings
from tests.conftest import csrf, signup
from tests.factories import cache_pickers, connected_org, rule_payload
from tests.slack_fixtures import API as SLACK_API
from tests.slack_fixtures import channel, ok, usergroup

RULES = "/api/v1/rules"


async def seed_groups(client: AsyncClient, chat_connection_id: str, count: int) -> None:
    """Populate the group picker cache with `count` distinct, creatable groups."""
    groups = [usergroup(f"S_G{i}", f"group-{i}", f"Group {i}") for i in range(count)]
    respx.post(f"{SLACK_API}/usergroups.list").mock(
        return_value=httpx.Response(200, json=ok(usergroups=groups))
    )
    await client.get(f"/api/v1/chat/connections/{chat_connection_id}/groups?refresh=true")


@pytest.fixture(autouse=True)
def provider_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


@respx.mock
async def test_create_a_rule(client: AsyncClient) -> None:
    ids = await connected_org(client)
    response = await client.post(RULES, json=rule_payload(ids), headers=csrf(client))

    assert response.status_code == 201, response.text
    rule = response.json()
    assert rule["name"] == "DevOps on-call"
    assert rule["escalation_levels"] == [1]
    assert rule["status"] == "pending"
    assert rule["enabled"] is True


@respx.mock
async def test_two_rules_cannot_manage_the_same_group(client: AsyncClient) -> None:
    """They would undo each other on every handoff."""
    ids = await connected_org(client)
    await client.post(RULES, json=rule_payload(ids), headers=csrf(client))

    clash = await client.post(
        RULES,
        json=rule_payload(ids, name="Second rule"),
        headers=csrf(client),
    )
    assert clash.status_code == 409
    assert "already manages" in clash.json()["detail"]


@respx.mock
async def test_an_unknown_schedule_is_refused(client: AsyncClient) -> None:
    ids = await connected_org(client)
    response = await client.post(
        RULES,
        json=rule_payload(ids, schedule_external_id="P_MISSING"),
        headers=csrf(client),
    )
    assert response.status_code == 400
    assert "Refresh the schedule list" in response.json()["detail"]


@respx.mock
async def test_an_unknown_user_group_is_refused(client: AsyncClient) -> None:
    ids = await connected_org(client)
    response = await client.post(
        RULES, json=rule_payload(ids, group_external_id="S_MISSING"), headers=csrf(client)
    )
    assert response.status_code == 400
    assert "Refresh the group list" in response.json()["detail"]


@respx.mock
async def test_a_channel_the_bot_is_not_in_is_refused(client: AsyncClient) -> None:
    """Slack silently drops posts to channels the app has not joined."""
    await signup(client)
    from tests.factories import connect_pagerduty, install_slack

    oncall = await connect_pagerduty(client)
    chat = await install_slack(client)
    await cache_pickers(client, oncall["id"], chat["id"], bot_in_channel=False)
    respx.reset()

    ids = {"oncall_connection_id": oncall["id"], "chat_connection_id": chat["id"]}
    response = await client.post(RULES, json=rule_payload(ids), headers=csrf(client))

    assert response.status_code == 400
    assert "not in #ops" in response.json()["detail"]


@respx.mock
async def test_quiet_mode_needs_no_channel(client: AsyncClient) -> None:
    ids = await connected_org(client)
    response = await client.post(
        RULES,
        json=rule_payload(ids, notify_channel_external_id=None, notify_on_change=False),
        headers=csrf(client),
    )
    assert response.status_code == 201
    assert response.json()["notify_on_change"] is False


@respx.mock
async def test_notify_on_change_requires_a_channel(client: AsyncClient) -> None:
    ids = await connected_org(client)
    response = await client.post(
        RULES,
        json=rule_payload(ids, notify_channel_external_id=None, notify_on_change=True),
        headers=csrf(client),
    )
    assert response.status_code == 400
    assert "Choose a channel" in response.json()["detail"]


@respx.mock
async def test_turning_on_notify_via_update_requires_a_channel(client: AsyncClient) -> None:
    ids = await connected_org(client)
    created = (
        await client.post(
            RULES,
            json=rule_payload(ids, notify_channel_external_id=None, notify_on_change=False),
            headers=csrf(client),
        )
    ).json()

    response = await client.patch(
        f"{RULES}/{created['id']}",
        json={"notify_on_change": True},
        headers=csrf(client),
    )
    assert response.status_code == 400
    assert "Choose a channel" in response.json()["detail"]


@respx.mock
async def test_clearing_the_channel_via_update_requires_notify_off(client: AsyncClient) -> None:
    ids = await connected_org(client)
    created = (await client.post(RULES, json=rule_payload(ids), headers=csrf(client))).json()
    assert created["notify_on_change"] is True

    response = await client.patch(
        f"{RULES}/{created['id']}",
        json={"notify_channel_external_id": None},
        headers=csrf(client),
    )
    assert response.status_code == 400
    assert "Choose a channel" in response.json()["detail"]


@respx.mock
async def test_a_quiet_rule_can_be_switched_to_notify_by_adding_a_channel(
    client: AsyncClient,
) -> None:
    ids = await connected_org(client)
    created = (
        await client.post(
            RULES,
            json=rule_payload(ids, notify_channel_external_id=None, notify_on_change=False),
            headers=csrf(client),
        )
    ).json()

    response = await client.patch(
        f"{RULES}/{created['id']}",
        json={"notify_on_change": True, "notify_channel_external_id": "C_OPS"},
        headers=csrf(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["notify_on_change"] is True
    assert response.json()["notify_channel_external_id"] == "C_OPS"


@respx.mock
async def test_escalation_levels_are_validated_and_deduplicated(client: AsyncClient) -> None:
    ids = await connected_org(client)

    empty = await client.post(
        RULES, json=rule_payload(ids, escalation_levels=[]), headers=csrf(client)
    )
    assert empty.status_code == 400

    zero = await client.post(
        RULES, json=rule_payload(ids, escalation_levels=[0]), headers=csrf(client)
    )
    assert zero.status_code == 400

    dupes = await client.post(
        RULES, json=rule_payload(ids, escalation_levels=[2, 1, 2]), headers=csrf(client)
    )
    assert dupes.status_code == 201
    assert dupes.json()["escalation_levels"] == [1, 2]


@respx.mock
async def test_updating_a_rule_reschedules_it(client: AsyncClient) -> None:
    ids = await connected_org(client)
    created = (await client.post(RULES, json=rule_payload(ids), headers=csrf(client))).json()

    updated = await client.patch(
        f"{RULES}/{created['id']}",
        json={"name": "Renamed", "enabled": False},
        headers=csrf(client),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["enabled"] is False


@respx.mock
async def test_deleting_a_rule_leaves_the_group_alone(client: AsyncClient) -> None:
    """We stop managing the handle; we do not empty it on the way out."""
    ids = await connected_org(client)
    created = (await client.post(RULES, json=rule_payload(ids), headers=csrf(client))).json()
    update_route = respx.post(f"{SLACK_API}/usergroups.users.update").mock(
        return_value=httpx.Response(200, json=ok())
    )

    deleted = await client.request("DELETE", f"{RULES}/{created['id']}", headers=csrf(client))
    assert deleted.status_code == 204
    assert (await client.get(RULES)).json() == []
    assert update_route.call_count == 0


@respx.mock
async def test_members_cannot_create_rules(client: AsyncClient, invitee: AsyncClient) -> None:
    ids = await connected_org(client)
    created = await client.post(
        "/api/v1/org/invites", json={"email": "bob@acme.dev"}, headers=csrf(client)
    )
    token = str(created.json()["accept_url"]).rsplit("/", 1)[-1]
    await invitee.post(
        "/api/v1/auth/invites/accept",
        json={"token": token, "name": "Bob", "password": "another-long-password"},
    )

    response = await invitee.post(RULES, json=rule_payload(ids), headers=csrf(invitee))
    assert response.status_code == 403
    # ...but they can see them.
    assert (await invitee.get(RULES)).status_code == 200


@respx.mock
async def test_a_rule_cannot_reference_another_orgs_connection(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    ids = await connected_org(client, email="owner@acme.dev")
    respx.reset()
    other = await connected_org(invitee, email="owner@globex.dev")

    stolen = await invitee.post(
        "/api/v1/rules",
        json=rule_payload({**other, "oncall_connection_id": ids["oncall_connection_id"]}),
        headers=csrf(invitee),
    )
    assert stolen.status_code == 404


@respx.mock
async def test_rules_are_scoped_per_org(client: AsyncClient, invitee: AsyncClient) -> None:
    ids = await connected_org(client, email="owner@acme.dev")
    await client.post(RULES, json=rule_payload(ids), headers=csrf(client))
    respx.reset()
    await connected_org(invitee, email="owner@globex.dev")

    assert (await invitee.get(RULES)).json() == []
    assert len((await client.get(RULES)).json()) == 1


@respx.mock
async def test_a_channel_refresh_makes_a_previously_refused_rule_valid(
    client: AsyncClient,
) -> None:
    """The error tells the user to invite the bot and refresh; that must work."""
    await signup(client)
    from tests.factories import connect_pagerduty, install_slack

    oncall = await connect_pagerduty(client)
    chat = await install_slack(client)
    await cache_pickers(client, oncall["id"], chat["id"], bot_in_channel=False)
    respx.reset()
    ids = {"oncall_connection_id": oncall["id"], "chat_connection_id": chat["id"]}
    assert (
        await client.post(RULES, json=rule_payload(ids), headers=csrf(client))
    ).status_code == 400

    respx.post(f"{SLACK_API}/conversations.list").mock(
        return_value=httpx.Response(
            200,
            json=ok(
                channels=[channel("C_OPS", "ops", is_member=True)],
                response_metadata={"next_cursor": ""},
            ),
        )
    )
    await client.get(f"/api/v1/chat/connections/{chat['id']}/channels?refresh=true")

    assert (
        await client.post(RULES, json=rule_payload(ids), headers=csrf(client))
    ).status_code == 201


@respx.mock
async def test_free_plan_limits_rule_creation(client: AsyncClient) -> None:
    ids = await connected_org(client)
    await seed_groups(client, ids["chat_connection_id"], 6)

    for i in range(5):
        response = await client.post(
            RULES,
            json=rule_payload(ids, name=f"Rule {i}", group_external_id=f"S_G{i}"),
            headers=csrf(client),
        )
        assert response.status_code == 201, response.text

    response = await client.post(
        RULES,
        json=rule_payload(ids, name="Rule 6", group_external_id="S_G5"),
        headers=csrf(client),
    )
    assert response.status_code == 403
    assert "free plan allows up to 5" in response.json()["detail"]


@respx.mock
async def test_upgrading_the_plan_raises_the_rule_limit(client: AsyncClient) -> None:
    ids = await connected_org(client)
    await seed_groups(client, ids["chat_connection_id"], 6)
    for i in range(5):
        await client.post(
            RULES,
            json=rule_payload(ids, name=f"Rule {i}", group_external_id=f"S_G{i}"),
            headers=csrf(client),
        )

    upgraded = await client.patch(
        "/api/v1/org/plan", json={"plan": "starter"}, headers=csrf(client)
    )
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json() == {
        "plan": "starter",
        "rule_limit": 100,
        "rule_count": 5,
        "tiers": [
            {"plan": "free", "rule_limit": 5},
            {"plan": "starter", "rule_limit": 100},
            {"plan": "premium", "rule_limit": 500},
        ],
    }

    response = await client.post(
        RULES,
        json=rule_payload(ids, name="Rule 6", group_external_id="S_G5"),
        headers=csrf(client),
    )
    assert response.status_code == 201, response.text


@respx.mock
async def test_member_cannot_change_plan(client: AsyncClient, invitee: AsyncClient) -> None:
    await connected_org(client)
    created = await client.post(
        "/api/v1/org/invites", json={"email": "bob@acme.dev"}, headers=csrf(client)
    )
    token = str(created.json()["accept_url"]).rsplit("/", 1)[-1]
    await invitee.post(
        "/api/v1/auth/invites/accept",
        json={"token": token, "name": "Bob", "password": "another-long-password"},
    )

    response = await invitee.patch(
        "/api/v1/org/plan", json={"plan": "starter"}, headers=csrf(invitee)
    )
    assert response.status_code == 403


@respx.mock
async def test_plan_cannot_be_downgraded_below_current_rule_count(client: AsyncClient) -> None:
    ids = await connected_org(client)
    await seed_groups(client, ids["chat_connection_id"], 6)
    await client.patch("/api/v1/org/plan", json={"plan": "starter"}, headers=csrf(client))
    for i in range(6):
        await client.post(
            RULES,
            json=rule_payload(ids, name=f"Rule {i}", group_external_id=f"S_G{i}"),
            headers=csrf(client),
        )

    response = await client.patch("/api/v1/org/plan", json={"plan": "free"}, headers=csrf(client))
    assert response.status_code == 400
    assert "more than the free plan's limit" in response.json()["detail"]


@respx.mock
async def test_open_license_mode_lifts_the_plan_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "license_mode", "open")
    ids = await connected_org(client)
    await seed_groups(client, ids["chat_connection_id"], 6)

    for i in range(6):
        response = await client.post(
            RULES,
            json=rule_payload(ids, name=f"Rule {i}", group_external_id=f"S_G{i}"),
            headers=csrf(client),
        )
        assert response.status_code == 201, response.text


@respx.mock
async def test_open_license_mode_disables_the_plan_endpoints(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "license_mode", "open")

    assert (await client.get("/api/v1/org/plan")).status_code == 404
    assert (
        await client.patch("/api/v1/org/plan", json={"plan": "starter"}, headers=csrf(client))
    ).status_code == 404


@respx.mock
async def test_get_plan_reports_usage_and_available_tiers(client: AsyncClient) -> None:
    ids = await connected_org(client)
    await seed_groups(client, ids["chat_connection_id"], 1)
    await client.post(
        RULES, json=rule_payload(ids, group_external_id="S_G0"), headers=csrf(client)
    )

    response = await client.get("/api/v1/org/plan")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "plan": "free",
        "rule_limit": 5,
        "rule_count": 1,
        "tiers": [
            {"plan": "free", "rule_limit": 5},
            {"plan": "starter", "rule_limit": 100},
            {"plan": "premium", "rule_limit": 500},
        ],
    }
