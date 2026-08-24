"""Sync rules: the mapping from an on-call schedule to a chat group handle."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.v1.schemas import (
    ProviderUserOut,
    ResolvedMemberOut,
    RulePreviewOut,
    SyncRuleOut,
)
from app.core.deps import CurrentUser, DbSession, require_role
from app.core.errors import Conflict, NotFound
from app.db.models import MANAGER_ROLES, RuleStatus, SyncRule, User
from app.db.repository import OrgScope
from app.domain.types import ProviderUser
from app.services import sync_rules
from app.services.identity_resolver import ResolvedMember
from app.services.sync_rules import RuleEvaluation

router = APIRouter(prefix="/rules", tags=["sync rules"])

RequireManager = Depends(require_role(*MANAGER_ROLES))


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    oncall_connection_id: uuid.UUID
    schedule_external_id: str = Field(min_length=1, max_length=120)
    escalation_levels: list[int] = Field(default_factory=lambda: [1], max_length=10)
    chat_connection_id: uuid.UUID
    group_external_id: str = Field(min_length=1, max_length=120)
    fallback_chat_user_id: str | None = Field(default=None, max_length=120)
    notify_channel_external_id: str | None = Field(default=None, max_length=120)
    notify_on_change: bool = True
    enabled: bool = True


class RuleUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    escalation_levels: list[int] | None = Field(default=None, max_length=10)
    fallback_chat_user_id: str | None = Field(default=None, max_length=120)
    notify_channel_external_id: str | None = Field(default=None, max_length=120)
    notify_on_change: bool | None = None
    enabled: bool | None = None


def _user_out(user: ProviderUser) -> ProviderUserOut:
    return ProviderUserOut(external_id=user.external_id, name=user.name, email=user.email)


def _member_out(member: ResolvedMember) -> ResolvedMemberOut:
    return ResolvedMemberOut(
        provider_user=_user_out(member.provider_user),
        chat_user_id=member.chat_user_id,
        chat_user_name=member.chat_user_name,
        source=member.source.value,
    )


def _preview_out(evaluation: RuleEvaluation, current: list[str]) -> RulePreviewOut:
    desired = set(evaluation.desired_member_ids)
    existing = set(current)
    # An empty desired set means the rule resolved to nobody and no fallback is
    # configured, so reconcile leaves the group untouched. Reporting a removal
    # here would promise a change that will never happen.
    would_write = bool(desired)
    return RulePreviewOut(
        evaluated_at=evaluation.evaluated_at,
        schedule_name=evaluation.schedule_name,
        on_call=[_user_out(user) for user in evaluation.on_call],
        resolved=[_member_out(member) for member in evaluation.resolved],
        unmapped=[_user_out(user) for user in evaluation.unmapped],
        desired_member_ids=evaluation.desired_member_ids,
        current_member_ids=current,
        would_write=would_write,
        would_add=sorted(desired - existing) if would_write else [],
        would_remove=sorted(existing - desired) if would_write else [],
        used_fallback=evaluation.used_fallback,
        next_change_at=evaluation.next_change_at,
        problems=evaluation.problems,
    )


@router.get("", response_model=list[SyncRuleOut])
async def list_rules(user: CurrentUser, db: DbSession) -> list[SyncRule]:
    scope = OrgScope(db, user.org_id)
    return sorted(await scope.list(SyncRule), key=lambda r: r.created_at)


@router.post("", response_model=SyncRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(payload: RuleIn, db: DbSession, actor: User = RequireManager) -> SyncRule:
    await sync_rules.validate_targets(
        db,
        org_id=actor.org_id,
        oncall_connection_id=payload.oncall_connection_id,
        schedule_external_id=payload.schedule_external_id,
        chat_connection_id=payload.chat_connection_id,
        group_external_id=payload.group_external_id,
        notify_channel_external_id=payload.notify_channel_external_id,
        escalation_levels=payload.escalation_levels,
    )

    scope = OrgScope(db, actor.org_id)
    clash = await db.scalar(
        scope.select(SyncRule).where(
            SyncRule.chat_connection_id == payload.chat_connection_id,
            SyncRule.group_external_id == payload.group_external_id,
        )
    )
    if clash is not None:
        # Two rules on one handle would undo each other on every handoff.
        raise Conflict(f"Another rule ({clash.name}) already manages that user group")

    rule = SyncRule(
        org_id=actor.org_id,
        name=payload.name.strip(),
        enabled=payload.enabled,
        oncall_connection_id=payload.oncall_connection_id,
        schedule_external_id=payload.schedule_external_id,
        escalation_levels=sorted(set(payload.escalation_levels)),
        chat_connection_id=payload.chat_connection_id,
        group_external_id=payload.group_external_id,
        fallback_chat_user_id=payload.fallback_chat_user_id,
        notify_channel_external_id=payload.notify_channel_external_id,
        notify_on_change=payload.notify_on_change,
        status=RuleStatus.PENDING,
        # Due immediately, so M5's beat picks it up on its next tick.
        next_run_at=datetime.now(UTC),
    )
    db.add(rule)
    await db.commit()
    return rule


@router.get("/{rule_id}", response_model=SyncRuleOut)
async def get_rule(rule_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SyncRule:
    rule = await OrgScope(db, user.org_id).get(SyncRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")
    return rule


@router.patch("/{rule_id}", response_model=SyncRuleOut)
async def update_rule(
    rule_id: uuid.UUID, payload: RuleUpdateIn, db: DbSession, actor: User = RequireManager
) -> SyncRule:
    rule = await OrgScope(db, actor.org_id).get(SyncRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")

    fields = payload.model_dump(exclude_unset=True)
    if "escalation_levels" in fields and fields["escalation_levels"] is not None:
        await sync_rules.validate_targets(
            db,
            org_id=actor.org_id,
            oncall_connection_id=rule.oncall_connection_id,
            schedule_external_id=rule.schedule_external_id,
            chat_connection_id=rule.chat_connection_id,
            group_external_id=rule.group_external_id,
            notify_channel_external_id=fields.get("notify_channel_external_id"),
            escalation_levels=fields["escalation_levels"],
        )
        fields["escalation_levels"] = sorted(set(fields["escalation_levels"]))

    for key, value in fields.items():
        setattr(rule, key, value)

    # Any change means the current state may no longer be right.
    rule.next_run_at = datetime.now(UTC)
    await db.commit()
    return rule


@router.post("/{rule_id}/preview", response_model=RulePreviewOut)
async def preview_rule(
    rule_id: uuid.UUID, db: DbSession, actor: User = RequireManager
) -> RulePreviewOut:
    """Dry run: who would be set, and what would change. Writes nothing."""
    rule = await OrgScope(db, actor.org_id).get(SyncRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")

    evaluation = await sync_rules.evaluate(db, rule)
    current = await sync_rules.current_group_members(db, rule)
    # Newly learned identity links are worth keeping even though nothing was
    # written to the chat workspace.
    await db.commit()
    return _preview_out(evaluation, current)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, db: DbSession, actor: User = RequireManager) -> None:
    rule = await OrgScope(db, actor.org_id).get(SyncRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")
    # The group keeps whoever it currently holds; we simply stop managing it.
    await db.delete(rule)
    await db.commit()
