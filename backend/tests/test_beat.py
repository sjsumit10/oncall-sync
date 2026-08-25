"""The scheduler tick.

Postgres holds the clock. These tests cover the claim itself and, importantly,
the startup guard: a scheduler whose role cannot bypass RLS would see zero due
rules and silently never fire a handoff, which looks healthy from every angle.
"""

from datetime import UTC, datetime, timedelta

import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from app.config import get_settings
from app.db.session import SessionLocal, get_admin_engine, set_current_org
from app.worker import beat
from tests.conftest import csrf
from tests.factories import connected_org, rule_payload

RULES = "/api/v1/rules"


@pytest.fixture(autouse=True)
def provider_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


async def set_next_run(rule_id: str, when: datetime | None) -> None:
    async with get_admin_engine().begin() as conn:
        await conn.execute(
            text("UPDATE sync_rules SET next_run_at = :when WHERE id = :id"),
            {"when": when, "id": rule_id},
        )


async def read_next_run(rule_id: str) -> datetime | None:
    async with get_admin_engine().connect() as conn:
        return await conn.scalar(
            text("SELECT next_run_at FROM sync_rules WHERE id = :id"), {"id": rule_id}
        )


@respx.mock
async def test_a_new_rule_is_due_immediately(client: AsyncClient) -> None:
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids), headers=csrf(client))

    claimed = await beat.claim_due_rules()
    assert [c.rule_id for c in claimed] == [created.json()["id"]]


@respx.mock
async def test_the_scheduler_sees_every_tenant(client: AsyncClient, invitee: AsyncClient) -> None:
    """Claiming is deliberately cross-tenant; the work that follows is not."""
    acme_ids = await connected_org(client, org="Acme", email="owner@acme.dev")
    acme = await client.post(RULES, json=rule_payload(acme_ids), headers=csrf(client))
    respx.reset()
    globex_ids = await connected_org(invitee, org="Globex", email="owner@globex.dev")
    globex = await invitee.post(RULES, json=rule_payload(globex_ids), headers=csrf(invitee))

    claimed = await beat.claim_due_rules()

    assert {c.rule_id for c in claimed} == {acme.json()["id"], globex.json()["id"]}
    # Each carries the org the worker must bind before doing anything.
    assert len({c.org_id for c in claimed}) == 2


@respx.mock
async def test_claiming_leases_the_rule_so_it_is_not_handed_out_twice(
    client: AsyncClient,
) -> None:
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids), headers=csrf(client))
    rule_id = created.json()["id"]

    first = await beat.claim_due_rules(lease_seconds=120)
    assert [c.rule_id for c in first] == [rule_id]

    second = await beat.claim_due_rules()
    assert second == [], "a claimed rule must not be re-issued during its lease"

    leased = await read_next_run(rule_id)
    assert leased is not None
    assert leased > datetime.now(UTC) + timedelta(seconds=60)


@respx.mock
async def test_a_rule_not_yet_due_is_left_alone(client: AsyncClient) -> None:
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids), headers=csrf(client))
    await set_next_run(created.json()["id"], datetime.now(UTC) + timedelta(hours=1))

    assert await beat.claim_due_rules() == []


@respx.mock
async def test_a_paused_rule_is_never_claimed(client: AsyncClient) -> None:
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids, enabled=False), headers=csrf(client))
    await set_next_run(created.json()["id"], datetime.now(UTC) - timedelta(minutes=1))

    assert await beat.claim_due_rules() == []


@respx.mock
async def test_an_expired_lease_makes_the_rule_eligible_again(client: AsyncClient) -> None:
    """A worker that dies mid-run must not strand its rule forever."""
    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids), headers=csrf(client))
    rule_id = created.json()["id"]

    await beat.claim_due_rules(lease_seconds=0)
    again = await beat.claim_due_rules()

    assert [c.rule_id for c in again] == [rule_id]


@respx.mock
async def test_a_successful_reconcile_schedules_the_next_handoff(
    client: AsyncClient,
) -> None:
    """The wake-up is taken from the schedule, not from a blind interval."""
    import httpx

    from tests.pagerduty_fixtures import API as PD_API
    from tests.pagerduty_fixtures import oncall, oncalls_page
    from tests.slack_fixtures import API as SLACK_API
    from tests.slack_fixtures import ok, slack_user

    ids = await connected_org(client)
    created = await client.post(RULES, json=rule_payload(ids), headers=csrf(client))
    rule_id = created.json()["id"]

    now = datetime.now(UTC).replace(microsecond=0)
    handoff = now + timedelta(minutes=2)
    respx.get(f"{PD_API}/oncalls").mock(
        return_value=httpx.Response(
            200,
            json=oncalls_page(
                [
                    oncall(
                        "PU1",
                        "Ada",
                        "ada@acme.dev",
                        (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                        handoff.isoformat().replace("+00:00", "Z"),
                    )
                ]
            ),
        )
    )
    respx.post(f"{SLACK_API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json=ok(user=slack_user("U_ADA", "Ada", "ada@acme.dev")))
    )
    respx.post(f"{SLACK_API}/usergroups.users.list").mock(
        return_value=httpx.Response(200, json=ok(users=[]))
    )
    respx.post(f"{SLACK_API}/usergroups.users.update").mock(
        return_value=httpx.Response(200, json=ok())
    )
    respx.post(f"{SLACK_API}/chat.postMessage").mock(
        return_value=httpx.Response(200, json=ok(channel="C_OPS", ts="1.1"))
    )

    await client.post(f"{RULES}/{rule_id}/sync", headers=csrf(client))

    scheduled = await read_next_run(rule_id)
    assert scheduled is not None
    # Just past the boundary, well inside the 5-minute safety interval.
    assert handoff < scheduled < handoff + timedelta(seconds=45)


async def test_startup_refuses_a_scheduler_that_cannot_see_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The silent-blindness failure mode has to be loud."""
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = get_settings()
    # The app role is deliberately NOSUPERUSER NOBYPASSRLS.
    unprivileged = create_async_engine(str(settings.database_url))
    monkeypatch.setattr(beat, "get_admin_engine", lambda: unprivileged)

    with pytest.raises(RuntimeError, match="cannot bypass row-level security"):
        await beat.assert_scheduler_can_see_rules()

    await unprivileged.dispose()


async def test_startup_accepts_the_admin_role() -> None:
    await beat.assert_scheduler_can_see_rules()


@respx.mock
async def test_rules_stay_invisible_to_the_wrong_tenant_despite_the_scheduler(
    client: AsyncClient, invitee: AsyncClient
) -> None:
    """The scheduler's reach must not leak into ordinary sessions."""
    from sqlalchemy import select

    from app.db.models import SyncRule

    acme_ids = await connected_org(client, org="Acme", email="owner@acme.dev")
    await client.post(RULES, json=rule_payload(acme_ids), headers=csrf(client))
    respx.reset()
    globex = await connected_org(invitee, org="Globex", email="owner@globex.dev")
    await invitee.post(RULES, json=rule_payload(globex), headers=csrf(invitee))

    globex_org = (await invitee.get("/api/v1/auth/me")).json()["organization"]["id"]
    set_current_org(globex_org)
    async with SessionLocal() as db:
        visible = list(await db.scalars(select(SyncRule)))
    assert [str(rule.org_id) for rule in visible] == [globex_org]
