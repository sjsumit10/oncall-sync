"""Teams install (PKCE + admin consent), team selection, and token refresh."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import get_settings
from app.core.http import ProviderAuthError
from app.db.models import ChatConnection, ConnectionStatus
from app.db.session import SessionLocal, set_current_org
from app.services import chat_connections
from tests.conftest import csrf, signup
from tests.factories import install_slack
from tests.teams_fixtures import API, TOKEN_URL, organization, token_response

CHAT = "/api/v1/chat"


@pytest.fixture
def teams_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "teams_client_id", "teams-client-id")
    monkeypatch.setattr(settings, "teams_client_secret", SecretStr("teams-client-secret"))


async def install_teams(client: AsyncClient) -> dict[str, object]:
    start = await client.post(f"{CHAT}/teams/install/start", headers=csrf(client))
    assert start.status_code == 200, start.text
    state = httpx.URL(start.json()["install_url"]).params["state"]

    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=token_response()))
    respx.get(f"{API}/organization").mock(return_value=httpx.Response(200, json=organization()))

    callback = await client.get(f"{CHAT}/teams/callback?code=install-code&state={state}")
    assert "installed=teams" in callback.headers["location"], callback.headers["location"]

    connections = (await client.get(f"{CHAT}/connections")).json()
    return connections[0]  # type: ignore[no-any-return]


@respx.mock
async def test_install_url_requests_admin_consent_and_pkce(
    client: AsyncClient, teams_app: None
) -> None:
    await signup(client)
    start = await client.post(f"{CHAT}/teams/install/start", headers=csrf(client))
    assert start.status_code == 200, start.text

    url = httpx.URL(start.json()["install_url"])
    assert url.params["prompt"] == "admin_consent"
    assert url.params["code_challenge_method"] == "S256"
    assert url.params["code_challenge"]


@respx.mock
async def test_install_stores_the_tenant_and_refresh_token(
    client: AsyncClient, teams_app: None
) -> None:
    session_body = await signup(client)
    connection = await install_teams(client)

    assert connection["kind"] == "teams"
    assert connection["team_name"] == "Acme Corp"
    assert connection["external_team_id"] == "TENANT1"
    assert connection["external_resource_id"] is None  # no Team picked yet

    set_current_org(session_body["organization"]["id"])  # type: ignore[index]
    async with SessionLocal() as db:
        row = await db.get(ChatConnection, uuid.UUID(str(connection["id"])))
    assert row is not None
    assert row.refresh_token_enc is not None
    assert row.token_expires_at is not None


@respx.mock
async def test_available_teams_lists_joined_teams(client: AsyncClient, teams_app: None) -> None:
    await signup(client)
    connection = await install_teams(client)

    respx.get(f"{API}/me/joinedTeams").mock(
        return_value=httpx.Response(
            200, json={"value": [{"id": "TEAM1", "displayName": "Engineering"}]}
        )
    )
    response = await client.get(f"{CHAT}/connections/{connection['id']}/available-teams")

    assert response.status_code == 200, response.text
    assert response.json() == [{"id": "TEAM1", "name": "Engineering"}]


@respx.mock
async def test_selecting_a_team_stores_the_resource_id(
    client: AsyncClient, teams_app: None
) -> None:
    await signup(client)
    connection = await install_teams(client)

    response = await client.patch(
        f"{CHAT}/connections/{connection['id']}/team",
        json={"team_id": "TEAM1"},
        headers=csrf(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["external_resource_id"] == "TEAM1"


@respx.mock
async def test_available_teams_404s_for_a_slack_connection(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))

    await signup(client)
    connection = await install_slack(client)

    response = await client.get(f"{CHAT}/connections/{connection['id']}/available-teams")
    assert response.status_code == 404


@respx.mock
async def test_credentials_for_refreshes_an_expiring_token(
    client: AsyncClient, teams_app: None
) -> None:
    session_body = await signup(client)
    connection = await install_teams(client)

    org_id = session_body["organization"]["id"]  # type: ignore[index]
    set_current_org(org_id)
    async with SessionLocal() as db:
        row = await db.get(ChatConnection, uuid.UUID(str(connection["id"])))
        assert row is not None
        row.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)  # already due

        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json=token_response(access_token="refreshed-token"))
        )
        credentials = await chat_connections.credentials_for(db, row)

    assert credentials.bot_token == "refreshed-token"


@respx.mock
async def test_credentials_for_marks_needs_reauth_when_refresh_is_rejected(
    client: AsyncClient, teams_app: None
) -> None:
    session_body = await signup(client)
    connection = await install_teams(client)

    org_id = session_body["organization"]["id"]  # type: ignore[index]
    set_current_org(org_id)
    async with SessionLocal() as db:
        row = await db.get(ChatConnection, uuid.UUID(str(connection["id"])))
        assert row is not None
        row.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)

        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(401, json={"error": "invalid_grant"})
        )
        with pytest.raises(ProviderAuthError):
            await chat_connections.credentials_for(db, row)

    set_current_org(org_id)
    async with SessionLocal() as db:
        refreshed = await db.get(ChatConnection, uuid.UUID(str(connection["id"])))
        assert refreshed is not None
        assert refreshed.status is ConnectionStatus.NEEDS_REAUTH
