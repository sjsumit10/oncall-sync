"""Sync rule evaluation.

``evaluate`` answers "what should this handle contain right now, and when does
that change" without writing anything. It is the read half of the reconcile loop,
so /preview and M5's reconciler see exactly the same result — a dry run that
diverged from the real thing would be worse than no dry run.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import BadRequest, Forbidden, NotFound
from app.db.models import (
    PLAN_RULE_LIMITS,
    ChatChannel,
    ChatConnection,
    ChatGroup,
    OncallConnection,
    OncallSchedule,
    Organization,
    SyncRule,
)
from app.domain.registry import get_chat_provider, get_oncall_provider
from app.domain.types import OncallSpan, ProviderUser
from app.services import chat_connections, identity_resolver, oncall_connections
from app.services.identity_resolver import ResolvedMember

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class RuleEvaluation:
    """What a rule resolves to at a moment in time. Nothing is written."""

    evaluated_at: datetime
    schedule_name: str
    on_call: list[ProviderUser]
    resolved: list[ResolvedMember]
    unmapped: list[ProviderUser]
    desired_member_ids: list[str]
    used_fallback: bool = False
    #: When the shift currently in force began.
    shift_start: datetime | None = None
    next_change_at: datetime | None = None
    #: Reasons the rule cannot do what it was asked to. Non-empty means degraded.
    problems: list[str] = field(default_factory=list)

    @property
    def is_degraded(self) -> bool:
        return bool(self.problems)


def _current_users(spans: list[OncallSpan], levels: list[int], at: datetime) -> list[ProviderUser]:
    wanted = set(levels)
    seen: dict[str, ProviderUser] = {}
    for span in spans:
        if span.level in wanted and span.covers(at):
            # One person can hold several levels; keep them once.
            seen.setdefault(span.user.external_id, span.user)
    return list(seen.values())


def _shift_start(spans: list[OncallSpan], levels: list[int], at: datetime) -> datetime | None:
    """The latest start among the shifts in force — i.e. when this handoff happened."""
    wanted = set(levels)
    starts = [span.start for span in spans if span.level in wanted and span.covers(at)]
    return max(starts) if starts else None


def _next_boundary(spans: list[OncallSpan], levels: list[int], at: datetime) -> datetime | None:
    """The earliest shift boundary after ``at``.

    This is what makes precise scheduling possible: the window fetch already
    knows when the next handoff is, so M5 can wake exactly then instead of
    polling blindly.
    """
    wanted = set(levels)
    boundaries = [
        moment
        for span in spans
        if span.level in wanted
        for moment in (span.start, span.end)
        if moment is not None and moment > at
    ]
    return min(boundaries) if boundaries else None


async def evaluate(
    db: AsyncSession, rule: SyncRule, *, at: datetime | None = None
) -> RuleEvaluation:
    settings = get_settings()
    now = at or datetime.now(UTC)

    oncall_connection = await db.get(OncallConnection, rule.oncall_connection_id)
    chat_connection = await db.get(ChatConnection, rule.chat_connection_id)
    if oncall_connection is None or chat_connection is None:
        raise NotFound("Rule references a connection that no longer exists")

    schedule = await db.scalar(
        select(OncallSchedule).where(
            OncallSchedule.connection_id == rule.oncall_connection_id,
            OncallSchedule.external_id == rule.schedule_external_id,
        )
    )

    credentials = await oncall_connections.credentials_for(db, oncall_connection)
    spans = await get_oncall_provider(oncall_connection.kind).get_oncall_window(
        credentials,
        rule.schedule_external_id,
        now - timedelta(minutes=1),
        now + timedelta(days=settings.oncall_window_days),
    )

    on_call = _current_users(spans, rule.escalation_levels, now)
    resolution = await identity_resolver.resolve(
        db,
        oncall_connection=oncall_connection,
        chat_connection=chat_connection,
        users=on_call,
    )

    evaluation = RuleEvaluation(
        evaluated_at=now,
        schedule_name=schedule.name if schedule else rule.schedule_external_id,
        on_call=on_call,
        resolved=resolution.resolved,
        unmapped=resolution.unmapped,
        desired_member_ids=resolution.chat_user_ids,
        shift_start=_shift_start(spans, rule.escalation_levels, now),
        next_change_at=_next_boundary(spans, rule.escalation_levels, now),
    )

    if resolution.unmapped:
        names = ", ".join(user.name for user in resolution.unmapped)
        evaluation.problems.append(f"No chat account matched for: {names}")

    if not evaluation.desired_member_ids:
        if not on_call:
            evaluation.problems.append("Nobody is on call for this schedule right now")
        if rule.fallback_chat_user_id:
            # Better a stale handle than one that pages nobody.
            evaluation.desired_member_ids = [rule.fallback_chat_user_id]
            evaluation.used_fallback = True
        else:
            evaluation.problems.append(
                "No fallback member is configured, so the handle will be left unchanged"
            )

    return evaluation


async def current_group_members(db: AsyncSession, rule: SyncRule) -> list[str]:
    chat_connection = await db.get(ChatConnection, rule.chat_connection_id)
    if chat_connection is None:
        raise NotFound("Rule references a workspace that no longer exists")
    credentials = await chat_connections.credentials_for(db, chat_connection)
    return await get_chat_provider(chat_connection.kind).get_group_members(
        credentials, rule.group_external_id
    )


async def assert_within_plan_limit(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Refuse a new rule once the org's plan quota is used up.

    No-op under license_mode "open": that deployment mode has no notion of a
    paid plan, so nothing to enforce.
    """
    if not get_settings().plans_enabled:
        return

    org = await db.get(Organization, org_id)
    if org is None:
        raise NotFound("Organization not found")

    limit = PLAN_RULE_LIMITS[org.plan]
    count = await db.scalar(select(func.count(SyncRule.id)).where(SyncRule.org_id == org_id))
    if (count or 0) >= limit:
        raise Forbidden(
            f"Your {org.plan.value} plan allows up to {limit} sync rules. "
            "Upgrade to create more."
        )


async def validate_targets(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    oncall_connection_id: uuid.UUID,
    schedule_external_id: str,
    chat_connection_id: uuid.UUID,
    group_external_id: str,
    notify_channel_external_id: str | None,
    notify_on_change: bool,
    escalation_levels: list[int],
) -> None:
    """Reject a rule that cannot possibly work, at the point it is written."""
    if not escalation_levels:
        raise BadRequest("Choose at least one escalation level")
    if any(level < 1 for level in escalation_levels):
        raise BadRequest("Escalation levels start at 1")
    if notify_on_change and not notify_channel_external_id:
        # Silently accepting this leaves a rule that can never announce a
        # handoff, with nothing in the UI ever telling you why.
        raise BadRequest(
            "Choose a channel to announce handoffs in, or turn off handoff announcements."
        )

    oncall_connection = await db.scalar(
        select(OncallConnection).where(
            OncallConnection.id == oncall_connection_id, OncallConnection.org_id == org_id
        )
    )
    if oncall_connection is None:
        raise NotFound("On-call connection not found")

    chat_connection = await db.scalar(
        select(ChatConnection).where(
            ChatConnection.id == chat_connection_id, ChatConnection.org_id == org_id
        )
    )
    if chat_connection is None:
        raise NotFound("Chat workspace not found")

    schedule = await db.scalar(
        select(OncallSchedule).where(
            OncallSchedule.connection_id == oncall_connection_id,
            OncallSchedule.external_id == schedule_external_id,
        )
    )
    if schedule is None:
        raise BadRequest("Unknown schedule. Refresh the schedule list and try again.")

    group = await db.scalar(
        select(ChatGroup).where(
            ChatGroup.chat_connection_id == chat_connection_id,
            ChatGroup.external_id == group_external_id,
        )
    )
    if group is None:
        raise BadRequest("Unknown user group. Refresh the group list and try again.")

    if notify_channel_external_id:
        channel = await db.scalar(
            select(ChatChannel).where(
                ChatChannel.chat_connection_id == chat_connection_id,
                ChatChannel.external_id == notify_channel_external_id,
            )
        )
        if channel is None:
            raise BadRequest("Unknown channel. Refresh the channel list and try again.")
        if not channel.bot_is_member:
            # Slack silently refuses to post where the bot has not been invited.
            raise BadRequest(
                f"The app is not in #{channel.name}. Invite it, refresh, and try again."
            )
