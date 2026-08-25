"""Scale behaviour of the scheduler.

The claim query runs every beat tick against every rule in the fleet, so it is the
one query whose cost has to stay flat as customers are added. These tests check
that it stays indexed and bounded at ~1k rules rather than degrading into a table
scan that only shows up in production.
"""

import time
import uuid

import pytest
from sqlalchemy import text

from app.db.session import get_admin_engine
from app.worker import beat

RULE_COUNT = 1000
#: Generous: this runs on a laptop against a container. The point is to catch an
#: order-of-magnitude regression, not to benchmark Postgres.
CLAIM_BUDGET_SECONDS = 1.0


async def seed_fleet(rules: int = RULE_COUNT, orgs: int = 20) -> None:
    """Insert a fleet directly.

    Deliberately plain SQL in three steps: the API is not what is under test, and
    a clever single statement here would be harder to trust than the thing it
    sets up.
    """
    suffix = uuid.uuid4().hex[:8]
    async with get_admin_engine().begin() as conn:
        org_ids = [
            row[0]
            for row in (
                await conn.execute(
                    text("""
                    INSERT INTO organizations (id, name, slug, created_at, updated_at)
                    SELECT gen_random_uuid(), 'Org ' || i, 'org-' || i || '-' || :suffix,
                           now(), now()
                    FROM generate_series(1, :orgs) AS i
                    RETURNING id
                    """),
                    {"orgs": orgs, "suffix": suffix},
                )
            ).all()
        ]

        pairs: list[dict[str, object]] = []
        for index, org_id in enumerate(org_ids):
            oncall_id = uuid.uuid4()
            chat_id = uuid.uuid4()
            await conn.execute(
                text("""
                INSERT INTO oncall_connections
                    (id, org_id, kind, auth_mode, display_name, credentials_enc,
                     status, created_at, updated_at)
                VALUES (:id, :org, 'pagerduty', 'api_key', 'PD', :blob, 'active', now(), now())
                """),
                {"id": oncall_id, "org": org_id, "blob": b"\x00"},
            )
            await conn.execute(
                text("""
                INSERT INTO chat_connections
                    (id, org_id, kind, external_team_id, team_name, bot_token_enc,
                     status, created_at, updated_at)
                VALUES (:id, :org, 'slack', :team, 'WS', :blob, 'active', now(), now())
                """),
                {"id": chat_id, "org": org_id, "team": f"T{index}-{suffix}", "blob": b"\x00"},
            )
            pairs.append({"org": org_id, "oncall": oncall_id, "chat": chat_id})

        # Staggered next_run_at so the claim has a realistic ordering to work with.
        for index in range(rules):
            pair = pairs[index % len(pairs)]
            await conn.execute(
                text("""
                INSERT INTO sync_rules
                    (id, org_id, name, enabled, oncall_connection_id, schedule_external_id,
                     escalation_levels, chat_connection_id, group_external_id,
                     notify_on_change, status, consecutive_failures, next_run_at,
                     created_at, updated_at)
                VALUES (gen_random_uuid(), :org, :name, true, :oncall, 'SCHED-1',
                        '{1}', :chat, :group, false, 'pending', 0,
                        now() - make_interval(secs => :offset), now(), now())
                """),
                {
                    "org": pair["org"],
                    "name": f"Rule {index}",
                    "oncall": pair["oncall"],
                    "chat": pair["chat"],
                    "group": f"GRP-{index}",
                    "offset": index % 600,
                },
            )

        # Fresh inserts leave the planner with stale statistics, which makes any
        # timing measured here unrepresentative.
        await conn.execute(text("ANALYZE sync_rules"))


async def rule_count() -> int:
    async with get_admin_engine().connect() as conn:
        return await conn.scalar(text("SELECT count(*) FROM sync_rules")) or 0


@pytest.mark.slow
async def test_the_index_covers_the_claim_predicate() -> None:
    """The scheduler's ordering and filter must be servable from the index.

    Deliberately not asserting the planner *chooses* it: on a small table a
    sequential scan is genuinely cheaper and Postgres is right to pick one. What
    matters is that the index matches the query shape, so the choice stays
    available as the fleet grows. Forcing seqscan off makes that explicit.
    """
    await seed_fleet()

    async with get_admin_engine().connect() as conn:
        await conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in (
                await conn.execute(
                    text("""
                    EXPLAIN SELECT id FROM sync_rules
                    WHERE enabled AND next_run_at IS NOT NULL AND next_run_at <= now()
                    ORDER BY next_run_at LIMIT 200
                    """)
                )
            ).all()
        )

    assert "ix_sync_rules_next_run_at" in plan, f"claim predicate is not indexed:\n{plan}"
    # Served in index order, so no sort of the whole fleet is needed.
    assert "Sort" not in plan, f"claim needs an explicit sort:\n{plan}"


@pytest.mark.slow
async def test_claiming_a_full_tick_is_fast_and_bounded() -> None:
    await seed_fleet()

    started = time.perf_counter()
    claimed = await beat.claim_due_rules()
    elapsed = time.perf_counter() - started

    assert len(claimed) == beat.MAX_RULES_PER_TICK, "a tick must take a bounded batch"
    assert elapsed < CLAIM_BUDGET_SECONDS, f"claim took {elapsed:.3f}s"
    # Each carries the org the worker binds before doing anything.
    assert all(rule.org_id for rule in claimed)


@pytest.mark.slow
async def test_successive_ticks_drain_the_backlog_without_repeating_work() -> None:
    await seed_fleet()

    seen: set[str] = set()
    ticks = 0
    while ticks < 12:
        claimed = await beat.claim_due_rules()
        if not claimed:
            break
        for rule in claimed:
            assert rule.rule_id not in seen, "a leased rule was handed out twice"
            seen.add(rule.rule_id)
        ticks += 1

    # The whole backlog drains, each rule exactly once, in bounded batches.
    assert len(seen) == await rule_count()
    assert ticks == -(-len(seen) // beat.MAX_RULES_PER_TICK)
