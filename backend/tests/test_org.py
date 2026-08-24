"""Members, invites and role enforcement."""

from httpx import AsyncClient

from tests.conftest import csrf, signup


async def invite(client: AsyncClient, email: str, role: str = "member") -> dict[str, object]:
    response = await client.post(
        "/api/v1/org/invites", json={"email": email, "role": role}, headers=csrf(client)
    )
    assert response.status_code == 201, response.text
    return response.json()


def token_from(created: dict[str, object]) -> str:
    return str(created["accept_url"]).rsplit("/", 1)[-1]


async def test_invite_and_accept_joins_the_same_org(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    owner = await signup(client)
    created = await invite(client, "bob@acme.dev")

    response = await invitee.post(
        "/api/v1/auth/invites/accept",
        json={
            "token": token_from(created),
            "name": "Bob",
            "password": "another-long-password",
        },
    )
    assert response.status_code == 201, response.text
    joined = response.json()

    assert joined["organization"]["id"] == owner["organization"]["id"]
    assert joined["user"]["role"] == "member"

    members = await client.get("/api/v1/org/members")
    assert {m["email"] for m in members.json()} == {"owner@acme.dev", "bob@acme.dev"}


async def test_invite_token_cannot_be_reused(client: AsyncClient, invitee: AsyncClient) -> None:
    await signup(client)
    created = await invite(client, "bob@acme.dev")
    body = {"token": token_from(created), "name": "Bob", "password": "another-long-password"}

    assert (await invitee.post("/api/v1/auth/invites/accept", json=body)).status_code == 201
    # The second attempt comes from a browser that now holds a session, so it
    # carries the CSRF header a real client would send.
    replay = await invitee.post("/api/v1/auth/invites/accept", json=body, headers=csrf(invitee))
    assert replay.status_code == 400


async def test_members_cannot_manage_invites(client: AsyncClient, invitee: AsyncClient) -> None:
    await signup(client)
    created = await invite(client, "bob@acme.dev")
    await invitee.post(
        "/api/v1/auth/invites/accept",
        json={"token": token_from(created), "name": "Bob", "password": "another-long-password"},
    )

    response = await invitee.post(
        "/api/v1/org/invites", json={"email": "carol@acme.dev"}, headers=csrf(invitee)
    )
    assert response.status_code == 403
    assert (await invitee.get("/api/v1/org/invites")).status_code == 403


async def test_only_an_owner_can_invite_an_admin(client: AsyncClient, invitee: AsyncClient) -> None:
    await signup(client)
    admin_invite = await invite(client, "admin@acme.dev", role="admin")
    await invitee.post(
        "/api/v1/auth/invites/accept",
        json={
            "token": token_from(admin_invite),
            "name": "Admin",
            "password": "another-long-password",
        },
    )

    # An admin may invite members...
    ok = await invitee.post(
        "/api/v1/org/invites", json={"email": "carol@acme.dev"}, headers=csrf(invitee)
    )
    assert ok.status_code == 201
    # ...but not another admin.
    denied = await invitee.post(
        "/api/v1/org/invites",
        json={"email": "dave@acme.dev", "role": "admin"},
        headers=csrf(invitee),
    )
    assert denied.status_code == 403


async def test_owner_role_cannot_be_invited(client: AsyncClient) -> None:
    await signup(client)
    response = await client.post(
        "/api/v1/org/invites",
        json={"email": "bob@acme.dev", "role": "owner"},
        headers=csrf(client),
    )
    assert response.status_code == 400


async def test_last_owner_cannot_be_demoted(client: AsyncClient) -> None:
    owner = await signup(client)
    response = await client.patch(
        f"/api/v1/org/members/{owner['user']['id']}",
        json={"role": "member"},
        headers=csrf(client),
    )
    assert response.status_code == 403
    assert (await client.get("/api/v1/auth/me")).json()["user"]["role"] == "owner"


async def test_removing_a_member_revokes_their_session(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    await signup(client)
    created = await invite(client, "bob@acme.dev")
    joined = await invitee.post(
        "/api/v1/auth/invites/accept",
        json={"token": token_from(created), "name": "Bob", "password": "another-long-password"},
    )
    member_id = joined.json()["user"]["id"]
    assert (await invitee.get("/api/v1/auth/me")).status_code == 200

    removed = await client.request(
        "DELETE", f"/api/v1/org/members/{member_id}", headers=csrf(client)
    )
    assert removed.status_code == 204
    assert (await invitee.get("/api/v1/auth/me")).status_code == 401
