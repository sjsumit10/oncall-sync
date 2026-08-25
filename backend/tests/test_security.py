"""Security review, expressed as tests.

Each of these encodes a property the design already claims. Writing them down
means a future change that quietly breaks one gets caught rather than shipped.
"""

import json
import re

import httpx
import pytest
import respx
import structlog
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import get_settings
from app.core.redaction import redact_processor
from tests.conftest import csrf, signup
from tests.factories import connected_org
from tests.slack_fixtures import API as SLACK_API
from tests.slack_fixtures import install_response

#: Anything that looks like it could be a credential must never appear in a body.
SECRET_SHAPED = re.compile(
    r"xox[bp]-|pd-secret|Bearer\s|refresh_token|client_secret|password_hash", re.IGNORECASE
)


@pytest.fixture(autouse=True)
def provider_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


class TestResponseHardening:
    async def test_security_headers_are_present(self, client: AsyncClient) -> None:
        response = await client.get("/health")

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["Referrer-Policy"] == "no-referrer"

    async def test_hsts_is_absent_over_plain_http(self, client: AsyncClient) -> None:
        """Asserting it locally would pin the browser to https://localhost for a year."""
        response = await client.get("/health")
        assert "Strict-Transport-Security" not in response.headers


class TestCredentialExposure:
    @respx.mock
    async def test_no_endpoint_returns_a_stored_credential(self, client: AsyncClient) -> None:
        await connected_org(client)

        for path in (
            "/api/v1/oncall/connections",
            "/api/v1/chat/connections",
            "/api/v1/auth/me",
            "/api/v1/org/members",
            "/api/v1/rules",
            "/api/v1/overview",
        ):
            body = (await client.get(path)).text
            assert not SECRET_SHAPED.search(body), f"{path} leaked something secret-shaped"

    @respx.mock
    async def test_an_invite_token_is_shown_once_and_never_listed(
        self, client: AsyncClient
    ) -> None:
        await signup(client)
        created = await client.post(
            "/api/v1/org/invites", json={"email": "bob@acme.dev"}, headers=csrf(client)
        )
        token = str(created.json()["accept_url"]).rsplit("/", 1)[-1]

        listed = (await client.get("/api/v1/org/invites")).text
        assert token not in listed, "the plaintext invite token must not be retrievable"

    @respx.mock
    async def test_the_session_cookie_is_http_only(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Ada",
                "email": "ada@acme.dev",
                "password": "correct-horse-battery",
            },
        )
        cookies = response.headers.get_list("set-cookie")
        session = next(c for c in cookies if c.startswith("oncall_session="))
        csrf_cookie = next(c for c in cookies if c.startswith("oncall_csrf="))

        assert "httponly" in session.lower()
        assert "samesite=lax" in session.lower()
        # The CSRF half of the pair is readable on purpose: the SPA echoes it back.
        assert "httponly" not in csrf_cookie.lower()


class TestLogRedaction:
    @pytest.mark.parametrize(
        "key",
        ["token", "bot_token", "api_key", "client_secret", "password", "code_verifier"],
    )
    def test_sensitive_keys_are_scrubbed(self, key: str) -> None:
        result = redact_processor(None, "info", {"event": "x", key: "super-secret"})
        assert result[key] == "[redacted]"

    def test_nested_secrets_are_scrubbed(self) -> None:
        result = redact_processor(
            None, "info", {"event": "x", "payload": {"access_token": "xoxb-real"}}
        )
        assert "xoxb-real" not in json.dumps(result)

    def test_ordinary_fields_survive(self) -> None:
        result = redact_processor(None, "info", {"event": "x", "rule_id": "r1", "count": 3})
        assert result["rule_id"] == "r1"
        assert result["count"] == 3

    @respx.mock
    async def test_a_real_install_does_not_log_its_tokens(
        self, client: AsyncClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End to end: run an install and grep everything that was logged."""
        structlog.configure(processors=[redact_processor, structlog.processors.JSONRenderer()])
        await signup(client)
        start = await client.post("/api/v1/chat/slack/install/start", headers=csrf(client))
        state = httpx.URL(start.json()["install_url"]).params["state"]
        respx.post(f"{SLACK_API}/oauth.v2.access").mock(
            return_value=httpx.Response(200, json=install_response())
        )
        await client.get(f"/api/v1/chat/slack/callback?code=c&state={state}")

        captured = capsys.readouterr()
        assert "xoxb-bot-token" not in captured.out + captured.err
        assert "xoxp-user-token" not in captured.out + captured.err


class TestAuthAbuse:
    async def test_login_is_throttled(self, client: AsyncClient) -> None:
        await signup(client)
        for _ in range(12):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@acme.dev", "password": "wrong-password-here"},
                headers=csrf(client),
            )
        assert "Too many attempts" in response.json()["detail"]

    async def test_a_wrong_password_and_an_unknown_email_look_the_same(
        self, client: AsyncClient
    ) -> None:
        """Response text must not disclose whether an address is registered."""
        await signup(client)
        wrong = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@acme.dev", "password": "not-the-password"},
            headers=csrf(client),
        )
        unknown = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@acme.dev", "password": "not-the-password"},
            headers=csrf(client),
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    @respx.mock
    async def test_the_oauth_callback_only_redirects_to_the_configured_app(
        self, client: AsyncClient
    ) -> None:
        """No user-supplied value reaches the Location header."""
        await signup(client)
        callback = await client.get(
            "/api/v1/chat/slack/callback?code=c&state=forged"
            "&redirect_uri=https://evil.example/steal"
        )
        location = callback.headers["location"]
        assert location.startswith(get_settings().web_base_url)
        assert "evil.example" not in location
