"""The dry run and identity matching.

/preview shares its evaluation code with M5's reconciler, so what it shows is
what will actually happen. These tests pin that contract.
"""

from datetime import UTC, datetime

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
IDENTITIES = "/api/v1/identities"
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def provider_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


def stamp(offset_hours: int) -> str:
    return (
        (NOW.replace(microsecond=0) + __import__("datetime").timedelta(hours=offset_hours))
        .isoformat()
        .replace("+00:00", "Z")
    )


def mock_oncall(entries: list[dict]) -> respx.Route:
    return respx.get(f"{PD_API}/oncalls").mock(
        return_value=httpx.Response(200, json=oncalls_page(entries))
    )


def mock_lookup(mapping: dict[str, dict | None]) -> respx.Route:
    def handler(request: httpx.Request) -> httpx.Response:
        email = dict(httpx.QueryParams(request.content.decode()))["email"]
        user = mapping.get(email)
        if user is None:
            return httpx.Response(200, json=err("users_not_found"))
        return httpx.Response(200, json=ok(user=user))

    return respx.post(f"{SLACK_API}/users.lookupByEmail").mock(side_effect=handler)


def mock_group_members(users: list[str]) -> respx.Route:
    return respx.post(f"{SLACK_API}/usergroups.users.list").mock(
        return_value=httpx.Response(200, json=ok(users=users))
    )


async def make_rule(client: AsyncClient, **overrides: object) -> dict:
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids, **overrides), headers=csrf(client))
    assert created.status_code == 201, created.text
    return {**created.json(), **ids}


@respx.mock
async def test_preview_resolves_the_on_call_person(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22))])
    mock_lookup({"ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev")})
    mock_group_members(["U_STALE"])

    preview = await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))
    assert preview.status_code == 200, preview.text
    body = preview.json()

    assert [u["name"] for u in body["on_call"]] == ["Ada"]
    assert body["desired_member_ids"] == ["U_ADA"]
    assert body["current_member_ids"] == ["U_STALE"]
    assert body["would_add"] == ["U_ADA"]
    assert body["would_remove"] == ["U_STALE"]
    assert body["problems"] == []
    assert body["schedule_name"] == "Primary"


@respx.mock
async def test_preview_writes_nothing_to_slack(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22))])
    mock_lookup({"ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev")})
    mock_group_members([])
    update = respx.post(f"{SLACK_API}/usergroups.users.update").mock(
        return_value=httpx.Response(200, json=ok())
    )
    post = respx.post(f"{SLACK_API}/chat.postMessage").mock(
        return_value=httpx.Response(200, json=ok())
    )

    await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))

    assert update.call_count == 0
    assert post.call_count == 0


@respx.mock
async def test_preview_reports_the_next_handoff_time(client: AsyncClient) -> None:
    """M5 schedules its wake-up from exactly this value."""
    rule = await make_rule(client)
    mock_oncall(
        [
            oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(6)),
            oncall("PU2", "Bob", "bob@acme.dev", stamp(6), stamp(30)),
        ]
    )
    mock_lookup(
        {
            "ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev"),
            "bob@acme.dev": slack_user("U_BOB", "Bob", "bob@acme.dev"),
        }
    )
    mock_group_members([])

    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()

    assert body["desired_member_ids"] == ["U_ADA"]
    assert body["next_change_at"] is not None
    assert body["next_change_at"].startswith(stamp(6)[:13])


@respx.mock
async def test_an_unmatched_person_degrades_the_rule(client: AsyncClient) -> None:
    """Email mismatch is the most common real failure; it must be loud."""
    rule = await make_rule(client)
    mock_oncall([oncall("PU9", "Contractor", "carol@vendor.dev", stamp(-1), stamp(11))])
    mock_lookup({})
    mock_group_members(["U_STALE"])

    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()

    assert [u["name"] for u in body["unmapped"]] == ["Contractor"]
    assert "No chat account matched" in body["problems"][0]
    # No fallback configured, so the handle is deliberately left alone.
    assert body["desired_member_ids"] == []
    assert body["would_write"] is False
    assert body["would_remove"] == []


@respx.mock
async def test_nobody_on_call_uses_the_fallback_rather_than_emptying(
    client: AsyncClient,
) -> None:
    rule = await make_rule(client, fallback_chat_user_id="U_LEAD")
    mock_oncall([])
    mock_group_members(["U_ADA"])

    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()

    assert body["desired_member_ids"] == ["U_LEAD"]
    assert body["used_fallback"] is True
    assert "Nobody is on call" in body["problems"][0]


@respx.mock
async def test_nobody_on_call_without_a_fallback_leaves_the_handle_untouched(
    client: AsyncClient,
) -> None:
    """A stale handle beats one that pages nobody."""
    rule = await make_rule(client)
    mock_oncall([])
    mock_group_members(["U_ADA"])

    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()

    assert body["desired_member_ids"] == []
    assert body["would_write"] is False
    assert body["would_remove"] == []
    assert any("left unchanged" in problem for problem in body["problems"])


@respx.mock
async def test_multiple_escalation_levels_are_unioned(client: AsyncClient) -> None:
    rule = await make_rule(client, escalation_levels=[1, 2])
    mock_oncall(
        [
            oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22), level=1),
            oncall("PU2", "Bob", "bob@acme.dev", stamp(-2), stamp(22), level=2),
        ]
    )
    mock_lookup(
        {
            "ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev"),
            "bob@acme.dev": slack_user("U_BOB", "Bob", "bob@acme.dev"),
        }
    )
    mock_group_members([])

    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()
    assert sorted(body["desired_member_ids"]) == ["U_ADA", "U_BOB"]


@respx.mock
async def test_one_person_on_two_levels_appears_once(client: AsyncClient) -> None:
    rule = await make_rule(client, escalation_levels=[1, 2])
    mock_oncall(
        [
            oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22), level=1),
            oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22), level=2),
        ]
    )
    mock_lookup({"ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev")})
    mock_group_members([])

    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()
    assert body["desired_member_ids"] == ["U_ADA"]


@respx.mock
async def test_a_learned_link_is_reused_without_another_lookup(client: AsyncClient) -> None:
    rule = await make_rule(client)
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22))])
    lookup = mock_lookup({"ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev")})
    mock_group_members([])

    await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))
    assert lookup.call_count == 1

    # A fully linked team costs no chat API calls at all.
    await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))
    assert lookup.call_count == 1


@respx.mock
async def test_a_manual_link_overrides_the_email_match(client: AsyncClient) -> None:
    rule = await make_rule(client)
    respx.get(f"{PD_API}/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "users": [{"id": "PU1", "name": "Ada", "email": "ada@acme.dev"}],
                "more": False,
            },
        )
    )
    mock_lookup({"ada@acme.dev": slack_user("U_EMAIL_MATCH", "Ada", "ada@acme.dev")})

    linked = await client.post(
        IDENTITIES,
        json={
            "oncall_connection_id": rule["oncall_connection_id"],
            "chat_connection_id": rule["chat_connection_id"],
            "provider_user_id": "PU1",
            "chat_user_id": "U_MANUAL",
        },
        headers=csrf(client),
    )
    assert linked.status_code == 201
    assert linked.json()["source"] == "manual"

    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22))])
    mock_group_members([])
    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()

    assert body["desired_member_ids"] == ["U_MANUAL"]
    assert body["resolved"][0]["source"] == "manual"


@respx.mock
async def test_directory_lists_people_with_their_link_status(client: AsyncClient) -> None:
    rule = await make_rule(client)
    respx.get(f"{PD_API}/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "users": [
                    {"id": "PU1", "name": "Ada", "email": "ada@acme.dev"},
                    {"id": "PU9", "name": "Contractor", "email": "carol@vendor.dev"},
                ],
                "more": False,
            },
        )
    )
    mock_lookup({"ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev")})
    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22))])
    mock_group_members([])
    # Previewing teaches the resolver about Ada.
    await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))

    query = (
        f"?oncall_connection_id={rule['oncall_connection_id']}"
        f"&chat_connection_id={rule['chat_connection_id']}"
    )
    everyone = (await client.get(f"{IDENTITIES}{query}")).json()
    assert {e["provider_user"]["name"]: e["link"] is not None for e in everyone} == {
        "Ada": True,
        "Contractor": False,
    }

    unmapped = (await client.get(f"{IDENTITIES}{query}&unmapped_only=true")).json()
    assert [e["provider_user"]["name"] for e in unmapped] == ["Contractor"]


@respx.mock
async def test_removing_a_link_makes_the_rule_degraded_again(client: AsyncClient) -> None:
    rule = await make_rule(client)
    respx.get(f"{PD_API}/users").mock(
        return_value=httpx.Response(
            200,
            json={"users": [{"id": "PU1", "name": "Ada", "email": "ada@acme.dev"}], "more": False},
        )
    )
    mock_lookup({"ada@acme.dev": slack_user("U_ADA", "Ada", "ada@acme.dev")})
    linked = await client.post(
        IDENTITIES,
        json={
            "oncall_connection_id": rule["oncall_connection_id"],
            "chat_connection_id": rule["chat_connection_id"],
            "provider_user_id": "PU1",
            "chat_user_id": "U_ADA",
        },
        headers=csrf(client),
    )
    respx.reset()

    deleted = await client.request(
        "DELETE", f"{IDENTITIES}/{linked.json()['id']}", headers=csrf(client)
    )
    assert deleted.status_code == 204

    mock_oncall([oncall("PU1", "Ada", "ada@acme.dev", stamp(-2), stamp(22))])
    mock_lookup({})  # Slack no longer finds them either
    mock_group_members(["U_ADA"])
    body = (await client.post(f"{RULES}/{rule['id']}/preview", headers=csrf(client))).json()

    assert [u["name"] for u in body["unmapped"]] == ["Ada"]
    assert body["would_remove"] == []


@respx.mock
async def test_another_org_cannot_preview_a_rule(client: AsyncClient, invitee: AsyncClient) -> None:
    rule = await make_rule(client)
    respx.reset()
    await connected_org(invitee, org="Globex", email="owner@globex.dev")

    response = await invitee.post(f"{RULES}/{rule['id']}/preview", headers=csrf(invitee))
    assert response.status_code == 404
