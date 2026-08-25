"""Org-wide run history and the health summary."""

import uuid

from fastapi import APIRouter, Query

from app.api.v1.schemas import ActivityRunOut, OverviewOut, SyncRunOut
from app.core.deps import CurrentUser, DbSession
from app.db.models import RunStatus, SyncRule, SyncRun
from app.db.repository import OrgScope
from app.services import health

router = APIRouter(tags=["activity"])


@router.get("/activity", response_model=list[ActivityRunOut])
async def list_activity(
    user: CurrentUser,
    db: DbSession,
    rule_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    limit: int = Query(default=50, le=200),
) -> list[ActivityRunOut]:
    """Every rule's runs, newest first.

    Joined to the rule name so the log reads on its own — chasing an id back to a
    rule is exactly the friction that stops people looking.
    """
    scope = OrgScope(db, user.org_id)
    query = (
        scope.select(SyncRun)
        .with_only_columns(SyncRun, SyncRule.name)
        .join(SyncRule, SyncRule.id == SyncRun.rule_id)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    )
    if rule_id is not None:
        query = query.where(SyncRun.rule_id == rule_id)
    if status is not None:
        query = query.where(SyncRun.status == status)

    rows = await db.execute(query)
    return [
        ActivityRunOut(**SyncRunOut.model_validate(run).model_dump(), rule_name=name)
        for run, name in rows.all()
    ]


@router.get("/overview", response_model=OverviewOut)
async def overview(user: CurrentUser, db: DbSession) -> OverviewOut:
    scope = OrgScope(db, user.org_id)
    counts = await health.org_health(db, scope)

    last_run = await db.scalar(
        scope.select(SyncRun)
        .with_only_columns(SyncRun.started_at)
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    # "A handoff happened" means the membership actually moved, not merely that a
    # run completed — a quiet week of successful no-op runs is not a handoff.
    last_handoff = await db.scalar(
        scope.select(SyncRun)
        .with_only_columns(SyncRun.started_at)
        .where(
            SyncRun.status == RunStatus.SUCCESS,
            SyncRun.new_members.isnot(None),
            SyncRun.previous_members.isnot(None),
            SyncRun.new_members != SyncRun.previous_members,
        )
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )

    return OverviewOut(
        rules_total=counts.rules_total,
        rules_by_status=counts.rules_by_status,
        rules_paused=counts.rules_paused,
        connections_needing_attention=counts.connections_needing_attention,
        last_handoff_at=last_handoff,
        last_run_at=last_run,
    )
