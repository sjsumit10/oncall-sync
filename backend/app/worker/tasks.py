"""ARQ task definitions."""

import uuid
from typing import Any

import structlog
from sqlalchemy import select

from app.db.models import RunTrigger, SyncRule
from app.db.session import SessionLocal, bind_org, set_current_org
from app.services import sync_engine
from app.worker import beat, queue

log = structlog.get_logger(__name__)


async def reconcile_rule(
    ctx: dict[str, Any], rule_id: str, org_id: str, trigger: str = RunTrigger.SCHEDULED.value
) -> str:
    """Reconcile one rule, inside its tenant."""
    org = uuid.UUID(org_id)
    async with SessionLocal() as db:
        # Bind before touching anything: the scheduler handed us an org id, and
        # every read and write from here runs under that tenant's RLS policies.
        await bind_org(db, org)
        rule = await db.scalar(
            select(SyncRule).where(SyncRule.id == uuid.UUID(rule_id), SyncRule.org_id == org)
        )
        if rule is None:
            log.info("reconcile.rule_gone", rule_id=rule_id)
            return "missing"

        try:
            run = await sync_engine.reconcile(db, rule, trigger=RunTrigger(trigger))
        finally:
            set_current_org(None)
        return str(run.status.value)


async def tick(ctx: dict[str, Any]) -> int:
    """Claim due rules and hand each to a worker."""
    claimed = await beat.claim_due_rules()
    for rule in claimed:
        await queue.enqueue_reconcile(rule.rule_id, rule.org_id, RunTrigger.SCHEDULED.value)
    if claimed:
        log.info("beat.claimed", count=len(claimed))
    return len(claimed)
