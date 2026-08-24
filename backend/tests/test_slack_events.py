"""The Slack events endpoint: signature verification and revocation handling."""

import hashlib
import hmac
import json
import time

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.config import get_settings
from app.db.models import ChatConnection, ConnectionStatus
from app.db.session import SessionLocal, set_current_org
from tests.conftest import csrf, signup
from tests.slack_fixtures import API, install_response

EVENTS = "/api/v1/webhooks/slack/events"
SIGNING_SECRET = "slack-signing-secret"


@pytest.fixture
def slack_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))
    monkeypatch.setattr(settings, "slack_signing_secret", SecretStr(SIGNING_SECRET))


def sign(body: bytes, *, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    digest = hmac.new(
        SIGNING_SECRET.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256
    ).hexdigest()
    return {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": f"v0={digest}",
        "Content-Type": "application/json",
    }


async def post_event(client: AsyncClient, payload: dict, **kwargs: object) -> httpx.Response:
    body = json.dumps(payload).encode()
    headers = kwargs.pop("headers", None) or sign(body, **kwargs)  # type: ignore[arg-type]
    return await client.post(EVENTS, content=body, headers=headers)


async def install_slack(client: AsyncClient) -> str:
    """Run the real install flow with a mocked Slack, returning the connection id."""
    start = await client.post("/api/v1/chat/slack/install/start", headers=csrf(client))
    assert start.status_code == 200, start.text
    state = httpx.URL(start.json()["install_url"]).params["state"]

    respx.post(f"{API}/oauth.v2.access").mock(
        return_value=httpx.Response(200, json=install_response())
    )
    callback = await client.get(f"/api/v1/chat/slack/callback?code=install-code&state={state}")
    assert "installed=slack" in callback.headers["location"]

    connections = (await client.get("/api/v1/chat/connections")).json()
    return str(connections[0]["id"])


@respx.mock
async def test_url_verification_handshake(client: AsyncClient, slack_app: None) -> None:
    response = await post_event(client, {"type": "url_verification", "challenge": "abc123"})

    assert response.status_code == 200
    assert response.json()["challenge"] == "abc123"


@respx.mock
async def test_an_unsigned_request_is_rejected(client: AsyncClient, slack_app: None) -> None:
    response = await client.post(
        EVENTS,
        content=json.dumps({"type": "url_verification", "challenge": "abc"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


@respx.mock
async def test_a_forged_signature_is_rejected(client: AsyncClient, slack_app: None) -> None:
    body = json.dumps({"type": "url_verification", "challenge": "abc"}).encode()
    headers = sign(body)
    headers["X-Slack-Signature"] = "v0=" + "0" * 64

    response = await client.post(EVENTS, content=body, headers=headers)
    assert response.status_code == 401


@respx.mock
async def test_a_replayed_old_request_is_rejected(client: AsyncClient, slack_app: None) -> None:
    """A correctly signed request from an hour ago is still a replay."""
    stale = str(int(time.time()) - 3600)
    response = await post_event(
        client, {"type": "url_verification", "challenge": "abc"}, timestamp=stale
    )
    assert response.status_code == 401


@respx.mock
async def test_a_signature_over_different_bytes_is_rejected(
    client: AsyncClient, slack_app: None
) -> None:
    """Verification must run on the raw body, not on re-serialized JSON."""
    signed_body = json.dumps({"type": "url_verification", "challenge": "original"}).encode()
    headers = sign(signed_body)
    tampered = json.dumps({"type": "url_verification", "challenge": "swapped"}).encode()

    response = await client.post(EVENTS, content=tampered, headers=headers)
    assert response.status_code == 401


@respx.mock
@pytest.mark.parametrize("event_type", ["app_uninstalled", "tokens_revoked"])
async def test_revocation_marks_the_workspace_for_reinstall(
    client: AsyncClient, slack_app: None, event_type: str
) -> None:
    body = await signup(client)
    connection_id = await install_slack(client)

    response = await post_event(
        client,
        {"type": "event_callback", "team_id": "T123", "event": {"type": event_type}},
    )
    assert response.status_code == 200

    set_current_org(body["organization"]["id"])  # type: ignore[index,arg-type]
    async with SessionLocal() as db:
        connection = await db.scalar(
            select(ChatConnection).where(ChatConnection.id == connection_id)
        )
    assert connection is not None
    assert connection.status is ConnectionStatus.NEEDS_REAUTH
    assert "reinstall" in (connection.last_error or "")


@respx.mock
async def test_an_event_for_an_unknown_workspace_is_a_quiet_success(
    client: AsyncClient, slack_app: None
) -> None:
    """Non-2xx makes Slack retry three times, so unknown workspaces must not error."""
    response = await post_event(
        client,
        {"type": "event_callback", "team_id": "T_UNKNOWN", "event": {"type": "app_uninstalled"}},
    )
    assert response.status_code == 200


@respx.mock
async def test_subteam_updated_is_accepted(client: AsyncClient, slack_app: None) -> None:
    await signup(client)
    await install_slack(client)

    response = await post_event(
        client,
        {
            "type": "event_callback",
            "team_id": "T123",
            "event": {"type": "subteam_updated", "subteam": {"id": "S1"}},
        },
    )
    assert response.status_code == 200
