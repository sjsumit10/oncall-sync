"""Chat workspace endpoints: install, pickers and tenant isolation."""

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.config import get_settings
from app.db.models import ChatConnection
from app.db.session import SessionLocal, set_current_org
from tests.conftest import csrf, signup
from tests.slack_fixtures import API, channel, err, install_response, ok, usergroup

CHAT = "/api/v1/chat"


@pytest.fixture
def slack_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


async def install(client: AsyncClient, **kwargs: object) -> dict[str, object]:
    start = await client.post(f"{CHAT}/slack/install/start", headers=csrf(client))
    assert start.status_code == 200, start.text
    state = httpx.URL(start.json()["install_url"]).params["state"]

    respx.post(f"{API}/oauth.v2.access").mock(
        return_value=httpx.Response(200, json=install_response(**kwargs))  # type: ignore[arg-type]
    )
    callback = await client.get(f"{CHAT}/slack/callback?code=install-code&state={state}")
    assert "installed=slack" in callback.headers["location"], callback.headers["location"]

    connections = (await client.get(f"{CHAT}/connections")).json()
    return connections[0]  # type: ignore[no-any-return]


@respx.mock
async def test_install_url_requests_both_bot_and_user_scopes(
    client: AsyncClient, slack_app: None
) -> None:
    """User scopes are the fallback for workspaces that restrict user groups."""
    await signup(client)
    start = await client.post(f"{CHAT}/slack/install/start", headers=csrf(client))

    url = httpx.URL(start.json()["install_url"])
    assert url.host == "slack.com"
    bot_scopes = set(url.params["scope"].split(","))
    assert {"usergroups:read", "usergroups:write", "chat:write", "users:read.email"} <= bot_scopes
    assert url.params["user_scope"] == "usergroups:write"
    assert url.params["state"]


@respx.mock
async def test_install_is_refused_without_a_configured_app(client: AsyncClient) -> None:
    await signup(client)
    response = await client.post(f"{CHAT}/slack/install/start", headers=csrf(client))
    assert response.status_code == 400


@respx.mock
async def test_install_stores_the_workspace(client: AsyncClient, slack_app: None) -> None:
    await signup(client)
    connection = await install(client)

    assert connection["team_name"] == "Acme"
    assert connection["external_team_id"] == "T123"
    assert connection["status"] == "active"
    assert connection["has_user_token"] is True
    # Tokens must never leave the server.
    assert "bot_token" not in connection
    assert "bot_token_enc" not in connection


@respx.mock
async def test_tokens_are_encrypted_at_rest(client: AsyncClient, slack_app: None) -> None:
    body = await signup(client)
    await install(client)

    set_current_org(body["organization"]["id"])  # type: ignore[index,arg-type]
    async with SessionLocal() as db:
        row = await db.scalar(select(ChatConnection))
    assert row is not None
    assert b"xoxb-bot-token" not in row.bot_token_enc
    assert row.user_token_enc is not None
    assert b"xoxp-user-token" not in row.user_token_enc


@respx.mock
async def test_installing_without_user_scopes_is_flagged(
    client: AsyncClient, slack_app: None
) -> None:
    """Without a user token there is no fallback if the workspace is locked down."""
    await signup(client)
    connection = await install(client, with_user_token=False)
    assert connection["has_user_token"] is False


@respx.mock
async def test_reinstall_keeps_the_same_connection_id(client: AsyncClient, slack_app: None) -> None:
    """Sync rules point at the connection, so a reconnect must not orphan them."""
    await signup(client)
    first = await install(client)
    respx.reset()
    second = await install(client)

    assert first["id"] == second["id"]
    assert len((await client.get(f"{CHAT}/connections")).json()) == 1


@respx.mock
async def test_reinstall_without_user_scopes_keeps_the_existing_user_token(
    client: AsyncClient, slack_app: None
) -> None:
    await signup(client)
    await install(client)
    respx.reset()
    again = await install(client, with_user_token=False)

    assert again["has_user_token"] is True


@respx.mock
async def test_install_callback_rejects_a_forged_state(
    client: AsyncClient, slack_app: None
) -> None:
    await signup(client)
    callback = await client.get(f"{CHAT}/slack/callback?code=c&state=forged")

    assert "error=invalid_state" in callback.headers["location"]
    assert (await client.get(f"{CHAT}/connections")).json() == []


@respx.mock
async def test_groups_are_fetched_then_cached(client: AsyncClient, slack_app: None) -> None:
    await signup(client)
    connection = await install(client)
    respx.reset()

    listing = respx.post(f"{API}/usergroups.list").mock(
        return_value=httpx.Response(
            200, json=ok(usergroups=[usergroup("S1", "devops-on-call", "DevOps")])
        )
    )

    first = await client.get(f"{CHAT}/connections/{connection['id']}/groups")
    assert [g["handle"] for g in first.json()] == ["devops-on-call"]
    assert listing.call_count == 1

    await client.get(f"{CHAT}/connections/{connection['id']}/groups")
    assert listing.call_count == 1

    await client.get(f"{CHAT}/connections/{connection['id']}/groups?refresh=true")
    assert listing.call_count == 2


@respx.mock
async def test_a_free_plan_workspace_gets_a_clear_message(
    client: AsyncClient, slack_app: None
) -> None:
    await signup(client)
    connection = await install(client)
    respx.reset()
    respx.post(f"{API}/usergroups.list").mock(
        return_value=httpx.Response(200, json=err("plan_upgrade_required"))
    )

    response = await client.get(f"{CHAT}/connections/{connection['id']}/groups")
    assert response.status_code == 400
    assert "Standard plan" in response.json()["detail"]


@respx.mock
async def test_channels_report_bot_membership(client: AsyncClient, slack_app: None) -> None:
    await signup(client)
    connection = await install(client)
    respx.reset()
    respx.post(f"{API}/conversations.list").mock(
        return_value=httpx.Response(
            200,
            json=ok(
                channels=[channel("C1", "ops"), channel("C2", "quiet", is_member=False)],
                response_metadata={"next_cursor": ""},
            ),
        )
    )

    channels = (await client.get(f"{CHAT}/connections/{connection['id']}/channels")).json()
    assert {c["name"]: c["bot_is_member"] for c in channels} == {"ops": True, "quiet": False}


@respx.mock
async def test_members_cannot_install(client: AsyncClient, invitee: AsyncClient) -> None:
    await signup(client)
    created = await client.post(
        "/api/v1/org/invites", json={"email": "bob@acme.dev"}, headers=csrf(client)
    )
    token = str(created.json()["accept_url"]).rsplit("/", 1)[-1]
    await invitee.post(
        "/api/v1/auth/invites/accept",
        json={"token": token, "name": "Bob", "password": "another-long-password"},
    )

    response = await invitee.post(f"{CHAT}/slack/install/start", headers=csrf(invitee))
    assert response.status_code == 403


@respx.mock
async def test_another_org_cannot_reach_the_workspace(
    client: AsyncClient, invitee: AsyncClient, slack_app: None
) -> None:
    await signup(client, email="owner@acme.dev")
    await signup(invitee, email="owner@globex.dev")
    connection = await install(client)

    assert (await invitee.get(f"{CHAT}/connections")).json() == []
    assert (await invitee.get(f"{CHAT}/connections/{connection['id']}/groups")).status_code == 404

    deleted = await invitee.request(
        "DELETE", f"{CHAT}/connections/{connection['id']}", headers=csrf(invitee)
    )
    assert deleted.status_code == 404


@respx.mock
async def test_rls_scopes_workspaces_without_the_repository_layer(
    client: AsyncClient, invitee: AsyncClient, slack_app: None
) -> None:
    acme = await signup(client, email="owner@acme.dev")
    await install(client)
    respx.reset()
    globex = await signup(invitee, email="owner@globex.dev")
    respx.post(f"{API}/oauth.v2.access").mock(
        return_value=httpx.Response(
            200, json=install_response(team_id="T999", team_name="Globex WS")
        )
    )
    start = await invitee.post(f"{CHAT}/slack/install/start", headers=csrf(invitee))
    state = httpx.URL(start.json()["install_url"]).params["state"]
    await invitee.get(f"{CHAT}/slack/callback?code=c&state={state}")

    for body in (acme, globex):
        org_id = body["organization"]["id"]  # type: ignore[index]
        set_current_org(org_id)  # type: ignore[arg-type]
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(ChatConnection)))
        assert [str(row.org_id) for row in rows] == [org_id]
