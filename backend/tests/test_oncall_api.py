"""Connection endpoints: API keys, OAuth, schedule caching and tenant isolation."""

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.config import get_settings
from app.db.models import OncallConnection
from app.db.session import SessionLocal, set_current_org
from app.providers.oncall.pagerduty.oauth import TOKEN_URL
from tests.conftest import csrf, signup
from tests.pagerduty_fixtures import API, schedule, schedules_page

PD = "/api/v1/oncall"


def mock_verify(total: int = 3) -> respx.Route:
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(200, json=schedules_page([])))
    return respx.get(f"{API}/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([], more=False) | {"total": total})
    )


async def connect_api_key(client: AsyncClient, key: str = "pd-secret-key") -> dict[str, object]:
    response = await client.post(
        f"{PD}/connections",
        json={"kind": "pagerduty", "api_key": key, "display_name": "Acme PagerDuty"},
        headers=csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def oauth_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend this deployment has a PagerDuty OAuth app registered."""
    settings = get_settings()
    monkeypatch.setattr(settings, "pagerduty_client_id", "client-id")
    monkeypatch.setattr(settings, "pagerduty_client_secret", SecretStr("client-secret"))


@respx.mock
async def test_providers_are_listed_from_the_registry(client: AsyncClient) -> None:
    await signup(client)
    providers = (await client.get(f"{PD}/providers")).json()

    assert [p["kind"] for p in providers] == ["pagerduty"]
    assert set(providers[0]["auth_modes"]) == {"oauth", "api_key"}
    assert providers[0]["supports_oauth"] is True
    # No OAuth app configured in the test environment.
    assert providers[0]["oauth_configured"] is False


@respx.mock
async def test_api_key_connection_is_verified_before_it_is_stored(client: AsyncClient) -> None:
    await signup(client)
    route = mock_verify()
    body = await connect_api_key(client)

    assert route.called
    assert body["status"] == "active"
    assert body["auth_mode"] == "api_key"
    # The credential must never come back out of the API.
    assert "api_key" not in body
    assert "credentials_enc" not in body


@respx.mock
async def test_a_credential_the_provider_rejects_is_not_stored(client: AsyncClient) -> None:
    await signup(client)
    respx.get(f"{API}/schedules").mock(return_value=httpx.Response(401, text="invalid key"))

    response = await client.post(
        f"{PD}/connections",
        json={"kind": "pagerduty", "api_key": "bad-key-value", "display_name": ""},
        headers=csrf(client),
    )
    assert response.status_code == 400
    assert (await client.get(f"{PD}/connections")).json() == []


@respx.mock
async def test_the_stored_credential_is_encrypted_at_rest(client: AsyncClient) -> None:
    session_body = await signup(client)
    mock_verify()
    await connect_api_key(client, key="pd-plaintext-should-not-appear")

    set_current_org(session_body["organization"]["id"])  # type: ignore[index,arg-type]
    async with SessionLocal() as db:
        row = await db.scalar(select(OncallConnection))
    assert row is not None
    assert b"pd-plaintext-should-not-appear" not in row.credentials_enc


@respx.mock
async def test_duplicate_api_key_connections_are_refused(client: AsyncClient) -> None:
    await signup(client)
    mock_verify()
    await connect_api_key(client)

    response = await client.post(
        f"{PD}/connections",
        json={"kind": "pagerduty", "api_key": "another-key", "display_name": ""},
        headers=csrf(client),
    )
    assert response.status_code == 409


@respx.mock
async def test_unknown_provider_is_a_404(client: AsyncClient) -> None:
    await signup(client)
    response = await client.post(
        f"{PD}/connections",
        json={"kind": "opsgenie", "api_key": "key-value", "display_name": ""},
        headers=csrf(client),
    )
    assert response.status_code == 404


@respx.mock
async def test_members_cannot_manage_connections(client: AsyncClient, invitee: AsyncClient) -> None:
    await signup(client)
    created = await client.post(
        "/api/v1/org/invites", json={"email": "bob@acme.dev"}, headers=csrf(client)
    )
    token = str(created.json()["accept_url"]).rsplit("/", 1)[-1]
    await invitee.post(
        "/api/v1/auth/invites/accept",
        json={"token": token, "name": "Bob", "password": "another-long-password"},
    )

    response = await invitee.post(
        f"{PD}/connections",
        json={"kind": "pagerduty", "api_key": "some-key", "display_name": ""},
        headers=csrf(invitee),
    )
    assert response.status_code == 403


@respx.mock
async def test_schedules_are_fetched_on_first_use_then_served_from_cache(
    client: AsyncClient,
) -> None:
    await signup(client)
    mock_verify()
    connection = await connect_api_key(client)
    respx.reset()

    listing = respx.get(f"{API}/schedules").mock(
        return_value=httpx.Response(
            200, json=schedules_page([schedule("P1", "Primary"), schedule("P2", "Secondary")])
        )
    )
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(200, json=schedules_page([])))

    first = await client.get(f"{PD}/connections/{connection['id']}/schedules")
    assert [s["name"] for s in first.json()] == ["Primary", "Secondary"]
    assert listing.call_count == 1

    # Second read is served from the cache — pickers must not cost an API call.
    second = await client.get(f"{PD}/connections/{connection['id']}/schedules")
    assert [s["name"] for s in second.json()] == ["Primary", "Secondary"]
    assert listing.call_count == 1

    # refresh=true goes back to the provider.
    await client.get(f"{PD}/connections/{connection['id']}/schedules?refresh=true")
    assert listing.call_count == 2


@respx.mock
async def test_refresh_prunes_schedules_deleted_upstream(client: AsyncClient) -> None:
    await signup(client)
    mock_verify()
    connection = await connect_api_key(client)
    respx.reset()

    respx.get(f"{API}/schedules").mock(
        side_effect=[
            httpx.Response(
                200, json=schedules_page([schedule("P1", "Primary"), schedule("P2", "Secondary")])
            ),
            httpx.Response(200, json=schedules_page([schedule("P1", "Primary renamed")])),
        ]
    )
    respx.get(f"{API}/v3/schedules").mock(return_value=httpx.Response(200, json=schedules_page([])))

    await client.get(f"{PD}/connections/{connection['id']}/schedules")
    after = await client.get(f"{PD}/connections/{connection['id']}/schedules?refresh=true")

    assert [s["external_id"] for s in after.json()] == ["P1"]
    assert after.json()[0]["name"] == "Primary renamed"


@respx.mock
async def test_another_org_cannot_see_or_touch_a_connection(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    await signup(client, email="owner@acme.dev")
    await signup(invitee, email="owner@globex.dev")
    mock_verify()
    connection = await connect_api_key(client)

    assert (await invitee.get(f"{PD}/connections")).json() == []
    assert (await invitee.get(f"{PD}/connections/{connection['id']}/schedules")).status_code == 404

    deleted = await invitee.request(
        "DELETE", f"{PD}/connections/{connection['id']}", headers=csrf(invitee)
    )
    assert deleted.status_code == 404
    assert len((await client.get(f"{PD}/connections")).json()) == 1


@respx.mock
async def test_rls_scopes_connections_even_without_the_repository_layer(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    acme = await signup(client, email="owner@acme.dev")
    globex = await signup(invitee, email="owner@globex.dev")
    mock_verify()
    await connect_api_key(client)
    await connect_api_key(invitee, key="globex-key")

    for body in (acme, globex):
        org_id = body["organization"]["id"]  # type: ignore[index]
        set_current_org(org_id)  # type: ignore[arg-type]
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(OncallConnection)))
        assert [str(row.org_id) for row in rows] == [org_id]


@respx.mock
async def test_oauth_start_is_refused_when_no_app_is_configured(client: AsyncClient) -> None:
    await signup(client)
    response = await client.post(f"{PD}/connections/pagerduty/oauth/start", headers=csrf(client))
    assert response.status_code == 400


@respx.mock
async def test_oauth_start_returns_an_authorize_url_with_pkce(
    client: AsyncClient, oauth_app: None
) -> None:
    await signup(client)
    response = await client.post(f"{PD}/connections/pagerduty/oauth/start", headers=csrf(client))
    assert response.status_code == 200

    url = httpx.URL(response.json()["authorize_url"])
    assert url.host == "identity.pagerduty.com"
    assert url.params["client_id"] == "client-id"
    assert url.params["code_challenge_method"] == "S256"
    assert url.params["state"]
    assert set(url.params["scope"].split()) == {"schedules.read", "oncalls.read", "users.read"}


@respx.mock
async def test_oauth_callback_creates_a_connection(client: AsyncClient, oauth_app: None) -> None:
    await signup(client)
    start = await client.post(f"{PD}/connections/pagerduty/oauth/start", headers=csrf(client))
    state = httpx.URL(start.json()["authorize_url"]).params["state"]

    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "pd-access",
                "refresh_token": "pd-refresh",
                "expires_in": 3600,
                "scope": "schedules.read oncalls.read users.read",
            },
        )
    )

    callback = await client.get(
        f"{PD}/connections/pagerduty/oauth/callback?code=auth-code&state={state}"
    )
    assert callback.status_code == 302
    assert "connected=pagerduty" in callback.headers["location"]

    # PKCE verifier must be sent, and never exposed to the browser.
    sent = dict(httpx.QueryParams(token_route.calls.last.request.content.decode()))
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "auth-code"
    assert sent["code_verifier"]

    connections = (await client.get(f"{PD}/connections")).json()
    assert len(connections) == 1
    assert connections[0]["auth_mode"] == "oauth"
    assert connections[0]["status"] == "active"


@respx.mock
async def test_oauth_callback_rejects_an_unknown_state(
    client: AsyncClient, oauth_app: None
) -> None:
    await signup(client)
    callback = await client.get(
        f"{PD}/connections/pagerduty/oauth/callback?code=auth-code&state=forged"
    )
    assert callback.status_code == 302
    assert "error=invalid_state" in callback.headers["location"]
    assert (await client.get(f"{PD}/connections")).json() == []


@respx.mock
async def test_oauth_state_cannot_be_replayed(client: AsyncClient, oauth_app: None) -> None:
    await signup(client)
    start = await client.post(f"{PD}/connections/pagerduty/oauth/start", headers=csrf(client))
    state = httpx.URL(start.json()["authorize_url"]).params["state"]
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
    )

    first = await client.get(f"{PD}/connections/pagerduty/oauth/callback?code=code-1&state={state}")
    assert "connected=pagerduty" in first.headers["location"]

    replay = await client.get(
        f"{PD}/connections/pagerduty/oauth/callback?code=code-2&state={state}"
    )
    assert "error=invalid_state" in replay.headers["location"]


@respx.mock
async def test_oauth_callback_in_a_different_browser_is_rejected(
    client: AsyncClient, invitee: AsyncClient, oauth_app: None
) -> None:
    """The state is bound to the session that started the flow."""
    await signup(client)
    start = await client.post(f"{PD}/connections/pagerduty/oauth/start", headers=csrf(client))
    state = httpx.URL(start.json()["authorize_url"]).params["state"]

    # invitee is a different browser with no session at all.
    callback = await invitee.get(
        f"{PD}/connections/pagerduty/oauth/callback?code=auth-code&state={state}"
    )
    assert "error=session_mismatch" in callback.headers["location"]
    assert (await client.get(f"{PD}/connections")).json() == []
