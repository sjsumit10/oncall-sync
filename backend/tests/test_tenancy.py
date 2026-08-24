"""Both belts of tenant isolation: the repository layer, then Postgres RLS."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Invite
from app.db.session import SessionLocal, set_current_org
from tests.conftest import csrf, signup


async def two_orgs(a: AsyncClient, b: AsyncClient) -> tuple[dict[str, object], dict[str, object]]:
    acme = await signup(a, org="Acme", email="owner@acme.dev")
    globex = await signup(b, org="Globex", email="owner@globex.dev")
    return acme, globex


async def test_members_of_another_org_are_invisible(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    await two_orgs(client, invitee)

    acme_members = (await client.get("/api/v1/org/members")).json()
    globex_members = (await invitee.get("/api/v1/org/members")).json()

    assert {m["email"] for m in acme_members} == {"owner@acme.dev"}
    assert {m["email"] for m in globex_members} == {"owner@globex.dev"}


async def test_cross_org_member_lookup_is_a_404_not_a_403(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    _, globex = await two_orgs(client, invitee)
    foreign_user_id = globex["user"]["id"]  # type: ignore[index]

    response = await client.patch(
        f"/api/v1/org/members/{foreign_user_id}", json={"role": "member"}, headers=csrf(client)
    )
    # 404, not 403: confirming a row exists in another tenant is itself a leak.
    assert response.status_code == 404


async def test_cross_org_invite_revocation_is_denied(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    await two_orgs(client, invitee)

    created = await invitee.post(
        "/api/v1/org/invites", json={"email": "new@globex.dev"}, headers=csrf(invitee)
    )
    foreign_invite_id = created.json()["invite"]["id"]

    response = await client.request(
        "DELETE", f"/api/v1/org/invites/{foreign_invite_id}", headers=csrf(client)
    )
    assert response.status_code == 404
    # And it really is still there for its owner.
    assert len((await invitee.get("/api/v1/org/invites")).json()) == 1


async def test_rls_blocks_a_query_that_skips_the_repository_layer(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    """The second belt.

    This issues a completely unscoped ``select(Invite)`` — the mistake the
    repository layer exists to prevent — and asserts Postgres filters it anyway.
    """
    acme, globex = await two_orgs(client, invitee)
    for browser in (client, invitee):
        domain = "acme" if browser is client else "globex"
        created = await browser.post(
            "/api/v1/org/invites",
            json={"email": f"new@{domain}.dev"},
            headers=csrf(browser),
        )
        assert created.status_code == 201, created.text

    acme_id = uuid.UUID(str(acme["organization"]["id"]))  # type: ignore[index]
    globex_id = uuid.UUID(str(globex["organization"]["id"]))  # type: ignore[index]

    set_current_org(acme_id)
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(Invite)))
    assert [row.org_id for row in rows] == [acme_id]

    set_current_org(globex_id)
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(Invite)))
    assert [row.org_id for row in rows] == [globex_id]

    # With no tenant bound, org_isolation matches nothing; only the narrow
    # invite_token_lookup policy applies, which is SELECT-only by design.
    set_current_org(None)
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(Invite)))
    assert len(rows) == 2
