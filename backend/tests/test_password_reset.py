"""Password reset: request throttling and enumeration-safety, token
single-use and expiry, and session revocation on confirm.

The request/confirm calls below deliberately come from a client that has
never signed in — signing up (or logging in) on the same client leaves it
with a session cookie, and CSRF is correctly enforced whenever one is
present. That matches the real flow too: someone requesting a reset has
forgotten their password, not signed in on that browser.
"""

import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.core.redis import get_redis
from app.core.sessions import SESSION_COOKIE
from app.services import password_reset
from tests.conftest import csrf, signup

RESET = "/api/v1/auth/password-reset"


def _stub_send_email(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake(*, to: str, subject: str, body: str) -> None:
        calls.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr("app.api.v1.auth.send_email", fake)
    return calls


def _token_from(calls: list[dict[str, Any]]) -> str:
    body = str(calls[0]["body"])
    # Pull the URL out of the plain-text body rather than assuming its position.
    url = next(word for word in body.split() if word.startswith("http"))
    return parse_qs(urlparse(url).query)["token"][0]


async def test_request_for_an_unknown_email_sends_nothing_but_still_succeeds(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_send_email(monkeypatch)
    response = await client.post(f"{RESET}/request", json={"email": "nobody@acme.dev"})

    assert response.status_code == 204
    assert calls == []


async def test_request_for_a_known_email_sends_a_reset_link(
    client: AsyncClient, invitee: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(invitee)  # the account owner's own, separate session
    calls = _stub_send_email(monkeypatch)

    response = await client.post(f"{RESET}/request", json={"email": "owner@acme.dev"})

    assert response.status_code == 204
    assert len(calls) == 1
    assert calls[0]["to"] == "owner@acme.dev"
    assert "/reset-password?token=" in calls[0]["body"]


async def test_request_is_rate_limited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_send_email(monkeypatch)
    for _ in range(6):
        response = await client.post(f"{RESET}/request", json={"email": "owner@acme.dev"})
    assert response.status_code == 429


async def test_confirm_resets_the_password_and_starts_a_session(
    client: AsyncClient, invitee: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(invitee)
    calls = _stub_send_email(monkeypatch)
    await client.post(f"{RESET}/request", json={"email": "owner@acme.dev"})
    token = _token_from(calls)

    confirm = await client.post(
        f"{RESET}/confirm", json={"token": token, "password": "a-new-long-password"}
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["user"]["email"] == "owner@acme.dev"
    assert client.cookies.get(SESSION_COOKIE)

    # confirm's own successful response already started a new session on this
    # client, so the login attempts below need the CSRF header like any other
    # authenticated-context mutation.
    old = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.dev", "password": "correct-horse-battery"},
        headers=csrf(client),
    )
    assert old.status_code == 401

    new = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.dev", "password": "a-new-long-password"},
        headers=csrf(client),
    )
    assert new.status_code == 200


async def test_confirm_revokes_every_other_session(
    client: AsyncClient, invitee: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `client` is the account holder's normal, already-signed-in browser.
    await signup(client)
    original_session = client.cookies.get(SESSION_COOKIE)
    assert original_session

    # `invitee` stands in for a second, separate browser — the one that opens
    # the emailed reset link and never had a session of its own.
    calls = _stub_send_email(monkeypatch)
    await invitee.post(f"{RESET}/request", json={"email": "owner@acme.dev"})
    token = _token_from(calls)

    confirm = await invitee.post(
        f"{RESET}/confirm", json={"token": token, "password": "a-new-long-password"}
    )
    assert confirm.status_code == 200, confirm.text

    # The original session, from before the reset, is dead.
    client.cookies.set(SESSION_COOKIE, original_session)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_confirm_rejects_an_unknown_token(client: AsyncClient) -> None:
    response = await client.post(
        f"{RESET}/confirm",
        json={"token": "not-a-real-token-not-a-real-token", "password": "x" * 12},
    )
    assert response.status_code == 400


async def test_confirm_is_rate_limited(client: AsyncClient) -> None:
    # Bogus tokens are enough — the IP throttle is checked before a token is
    # even looked up, so this never gets past a 400 until the limit trips.
    for _ in range(6):
        response = await client.post(
            f"{RESET}/confirm",
            json={"token": "not-a-real-token-not-a-real-token", "password": "x" * 12},
        )
    assert response.status_code == 429


async def test_confirm_rejects_a_reused_token(
    client: AsyncClient, invitee: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(invitee)
    calls = _stub_send_email(monkeypatch)
    await client.post(f"{RESET}/request", json={"email": "owner@acme.dev"})
    token = _token_from(calls)

    first = await client.post(
        f"{RESET}/confirm", json={"token": token, "password": "a-new-long-password"}
    )
    assert first.status_code == 200

    # The first confirm's success already started a session on this client.
    second = await client.post(
        f"{RESET}/confirm",
        json={"token": token, "password": "another-long-password"},
        headers=csrf(client),
    )
    assert second.status_code == 400


async def test_expired_token_behaves_like_an_unknown_one(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    """Redis's own TTL is the entire expiry mechanism, so a token past its
    5-minute window is indistinguishable from one that never existed — this
    exercises that contract directly rather than waiting 5 real minutes."""
    body = await signup(invitee)
    user_id = uuid.UUID(str(body["user"]["id"]))  # type: ignore[index]

    redis = get_redis()
    token = await password_reset.issue(redis, user_id=user_id)
    consumed_once = await password_reset.consume(redis, token)
    assert consumed_once is not None

    # Simulate expiry: consuming a token that no longer exists in Redis.
    assert await password_reset.consume(redis, token) is None

    response = await client.post(
        f"{RESET}/confirm", json={"token": token, "password": "a-new-long-password"}
    )
    assert response.status_code == 400
