"""Sync rules: the mapping from an on-call schedule to a chat group handle."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.api.v1.schemas import (
    MessagePreviewOut,
    ProviderUserOut,
    ResolvedMemberOut,
    RulePreviewOut,
    SyncRuleOut,
    SyncRunOut,
)
from app.core.deps import CurrentUser, DbSession, require_role
from app.core.errors import BadRequest, Conflict, NotFound
from app.db.models import (
    MANAGER_ROLES,
    ChatConnection,
    RuleStatus,
    RunTrigger,
    SyncRule,
    SyncRun,
    User,
)
from app.db.repository import OrgScope
from app.domain.registry import get_chat_provider
from app.domain.types import Announcement, ProviderUser
from app.services import sync_engine, sync_rules, templating
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
    message_template: str | None = Field(default=None, max_length=templating.MAX_TEMPLATE_LENGTH)
    enabled: bool = True


class RuleUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    escalation_levels: list[int] | None = Field(default=None, max_length=10)
    fallback_chat_user_id: str | None = Field(default=None, max_length=120)
    notify_channel_external_id: str | None = Field(default=None, max_length=120)
    notify_on_change: bool | None = None
    message_template: str | None = Field(default=None, max_length=templating.MAX_TEMPLATE_LENGTH)
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
        shift_start=evaluation.shift_start,
        next_change_at=evaluation.next_change_at,
        problems=evaluation.problems,
    )


def _assert_template_ok(template: str | None) -> None:
    """Reject a broken template when it is written, not when it fires at 3am."""
    if not template:
        return
    problems = templating.validate(template)
    if problems:
        raise BadRequest(" ".join(problems))


@router.get("", response_model=list[SyncRuleOut])
async def list_rules(user: CurrentUser, db: DbSession) -> list[SyncRule]:
    scope = OrgScope(db, user.org_id)
    return sorted(await scope.list(SyncRule), key=lambda r: r.created_at)


# Declared before the /{rule_id}/... routes: FastAPI matches in declaration
# order, and otherwise "template" is read as a rule id.
class MessagePreviewIn(BaseModel):
    """A template to render. Omit it to preview the built-in default."""

    template: str | None = Field(default=None, max_length=templating.MAX_TEMPLATE_LENGTH)


@router.post("/template/preview", response_model=MessagePreviewOut)
async def preview_message(
    payload: MessagePreviewIn, db: DbSession, actor: User = RequireManager
) -> MessagePreviewOut:
    """Render a template against sample data.

    Sample rather than live data on purpose: this backs a live editor, and going
    to PagerDuty and Slack on every keystroke would be both slow and rude.
    """
    problems = templating.validate(payload.template) if payload.template else []
    if problems:
        return MessagePreviewOut(
            text="",
            blocks=[],
            problems=problems,
            variables=templating.SAMPLE_CONTEXT.as_dict(),
        )

    text, render_problem = templating.safe_render(payload.template, templating.SAMPLE_CONTEXT)
    announcement = Announcement(
        text=text,
        kind="handoff",
        schedule_name=templating.SAMPLE_CONTEXT.schedule_name,
        handle=templating.SAMPLE_CONTEXT.handle,
    )

    # Ask the workspace's own provider to render it, so the preview is exactly
    # what would be posted and no vendor markup is built here.
    connection = await db.scalar(
        OrgScope(db, actor.org_id).select(ChatConnection).order_by(ChatConnection.created_at)
    )
    blocks: list[dict[str, Any]] = []
    if connection is not None:
        _, rendered = get_chat_provider(connection.kind).render_announcement(announcement)
        blocks = [dict(block) for block in rendered]

    return MessagePreviewOut(
        text=text,
        blocks=blocks,
        problems=[render_problem] if render_problem else [],
        variables=templating.SAMPLE_CONTEXT.as_dict(),
    )


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

    _assert_template_ok(payload.message_template)

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
        message_template=payload.message_template,
        status=RuleStatus.PENDING,
        # Due immediately. Written as SQL now() rather than the app server's
        # clock: the scheduler compares next_run_at against the database's clock,
        # and any skew between the two would leave a "due" rule unclaimed.
        next_run_at=func.now(),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
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
    if "message_template" in fields:
        _assert_template_ok(fields["message_template"])
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

    # Any change means the current state may no longer be right. Server clock,
    # for the same reason as above.
    rule.next_run_at = func.now()
    await db.commit()
    await db.refresh(rule)
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


@router.post("/{rule_id}/sync", response_model=SyncRunOut)
async def sync_now(rule_id: uuid.UUID, db: DbSession, actor: User = RequireManager) -> SyncRun:
    """Reconcile immediately, in-request.

    Runs the same code the scheduler runs, so what a user sees here is exactly
    what happens on a handoff.
    """
    rule = await OrgScope(db, actor.org_id).get(SyncRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")
    return await sync_engine.reconcile(db, rule, trigger=RunTrigger.MANUAL)


@router.get("/{rule_id}/runs", response_model=list[SyncRunOut])
async def list_runs(
    rule_id: uuid.UUID, user: CurrentUser, db: DbSession, limit: int = 25
) -> list[SyncRun]:
    scope = OrgScope(db, user.org_id)
    if await scope.get(SyncRule, rule_id) is None:
        raise NotFound("Rule not found")
    return list(
        await db.scalars(
            scope.select(SyncRun)
            .where(SyncRun.rule_id == rule_id)
            .order_by(SyncRun.started_at.desc())
            .limit(min(limit, 100))
        )
    )
