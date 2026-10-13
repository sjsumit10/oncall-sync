"""Signup, login, session lifetime and CSRF."""

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.core.sessions import SESSION_COOKIE
from tests.conftest import csrf, signup


async def test_signup_creates_org_with_owner(client: AsyncClient) -> None:
    body = await signup(client)

    assert body["user"]["role"] == "owner"
    assert body["user"]["email"] == "owner@acme.dev"
    # No org name is collected at signup — the org starts named after the
    # owner's email and can be renamed later from Settings.
    assert body["organization"]["name"] == "owner@acme.dev"
    assert body["organization"]["slug"]
    assert client.cookies.get(SESSION_COOKIE)

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == body["user"]["id"]


async def test_session_reports_plans_enabled_from_license_mode(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = await signup(client)
    assert body["plans_enabled"] is True

    monkeypatch.setattr(get_settings(), "license_mode", "open")
    me = await client.get("/api/v1/auth/me")
    assert me.json()["plans_enabled"] is False


async def test_signup_rejects_duplicate_email(client: AsyncClient) -> None:
    await signup(client)
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Bob",
            "email": "OWNER@acme.dev",  # case-insensitive collision
            "password": "correct-horse-battery",
        },
        headers=csrf(client),
    )
    assert response.status_code == 409


async def test_signup_is_rate_limited(client: AsyncClient) -> None:
    await signup(client)  # 1st attempt, succeeds and starts a session
    response = None
    for _ in range(5):  # 5 more: still under SIGNUP_ATTEMPT_LIMIT (5) until the last
        response = await client.post(
            "/api/v1/auth/signup",
            json={"name": "Bob", "email": "owner@acme.dev", "password": "correct-horse-battery"},
            headers=csrf(client),
        )
    assert response is not None
    assert response.status_code == 429


async def test_signup_rejects_short_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Ada",
            "email": "ada@acme.dev",
            "password": "short",
        },
    )
    assert response.status_code == 422


async def test_login_and_logout(client: AsyncClient) -> None:
    await signup(client)
    await client.post("/api/v1/auth/logout", headers=csrf(client))
    assert await anonymous_me(client) == 401

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.dev", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    await signup(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.dev", "password": "not-the-password"},
        headers=csrf(client),
    )
    assert response.status_code == 401


async def test_login_is_rate_limited(client: AsyncClient) -> None:
    await signup(client)
    response = None
    for _ in range(11):  # LOGIN_ATTEMPT_LIMIT is 10
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@acme.dev", "password": "not-the-password"},
            headers=csrf(client),
        )
    assert response is not None
    assert response.status_code == 401
    # Distinct from a wrong-password 401 — same status code (so a client
    # can't distinguish "wrong password" from "rate limited" from the status
    # alone), but the message says which actually happened.
    assert "too many attempts" in response.json()["detail"].lower()


async def test_logout_revokes_the_session_server_side(client: AsyncClient) -> None:
    await signup(client)
    stolen = client.cookies.get(SESSION_COOKIE)
    await client.post("/api/v1/auth/logout", headers=csrf(client))

    # Replaying the cookie value must fail: session state lives in Redis, not the cookie.
    client.cookies.set(SESSION_COOKIE, stolen or "")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_mutation_without_csrf_header_is_rejected(client: AsyncClient) -> None:
    await signup(client)
    response = await client.post(
        "/api/v1/org/invites", json={"email": "new@acme.dev", "role": "member"}
    )
    assert response.status_code == 403

    response = await client.post(
        "/api/v1/org/invites",
        json={"email": "new@acme.dev", "role": "member"},
        headers=csrf(client),
    )
    assert response.status_code == 201


async def anonymous_me(client: AsyncClient) -> int:
    return (await client.get("/api/v1/auth/me")).status_code
