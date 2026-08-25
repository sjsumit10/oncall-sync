"""The scheduler tick.

Postgres holds the clock: every rule carries ``next_run_at``, and this claims the
ones that have come due. Delayed jobs never live only in Redis, so losing Redis
costs at most one tick rather than silently dropping every future handoff.

Claiming spans tenants — that is what a scheduler is — so it runs on the
privileged admin connection. Everything downstream binds an org and works under
RLS like any request.
"""

from dataclasses import dataclass

import structlog
from sqlalchemy import text

from app.db.session import get_admin_engine

log = structlog.get_logger(__name__)

#: How long a claimed rule is held before it becomes eligible again. Long enough
#: to cover a slow reconcile, short enough that a lost worker retries promptly.
LEASE_SECONDS = 120
MAX_RULES_PER_TICK = 200

_CLAIM_SQL = text("""
    WITH due AS (
        SELECT id
        FROM sync_rules
        WHERE enabled
          AND next_run_at IS NOT NULL
          AND next_run_at <= now()
        ORDER BY next_run_at
        LIMIT :max_rules
        FOR UPDATE SKIP LOCKED
    )
    UPDATE sync_rules
    SET next_run_at = now() + make_interval(secs => :lease_seconds)
    WHERE id IN (SELECT id FROM due)
    RETURNING id, org_id
""")


@dataclass(frozen=True, slots=True)
class ClaimedRule:
    rule_id: str
    org_id: str


async def claim_due_rules(
    *, max_rules: int = MAX_RULES_PER_TICK, lease_seconds: int = LEASE_SECONDS
) -> list[ClaimedRule]:
    """Take ownership of every rule whose time has come.

    SKIP LOCKED lets several beats run without handing the same rule to two
    workers, and the lease means a worker that dies mid-run does not strand its
    rule forever.
    """
    async with get_admin_engine().begin() as conn:
        rows = await conn.execute(
            _CLAIM_SQL, {"max_rules": max_rules, "lease_seconds": lease_seconds}
        )
        return [ClaimedRule(rule_id=str(row[0]), org_id=str(row[1])) for row in rows]


async def assert_scheduler_can_see_rules() -> None:
    """Fail loudly at startup if the admin role is subject to RLS.

    Without this the symptom is a scheduler that quietly sees zero due rules and
    never fires a handoff — the worst possible failure for this product, because
    everything looks healthy while nothing happens.
    """
    async with get_admin_engine().connect() as conn:
        can_bypass = await conn.scalar(
            text("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user")
        )
    if not can_bypass:
        log.error(
            "scheduler.cannot_bypass_rls",
            hint=(
                "DATABASE_ADMIN_URL's role needs BYPASSRLS (or superuser) or the "
                "scheduler will see no rules and no handoff will ever run."
            ),
        )
        raise RuntimeError(
            "The scheduler's database role cannot bypass row-level security; "
            "no rule would ever be claimed."
        )
