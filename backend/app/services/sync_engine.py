"""The reconcile loop — the heart of the product.

Provider-agnostic by construction: it talks to `OncallProvider` and `ChatProvider`
through the registry and never names a vendor.

Two distinctions carry most of the correctness:

* **Writing vs announcing.** Membership is rewritten whenever the chat provider
  disagrees with
  what the rule says it should be, including when a human edited the group
  by hand. A message is posted only when the *on-call people actually changed*.
  Repairing drift must never fabricate a handoff in the channel.
* **Degraded vs failed.** A rule that resolves to nobody has not failed — it has
  nothing safe to write. It leaves the handle exactly as it is rather than
  emptying it, because a stale handle still pages a human and an empty one pages
  no one.
"""

import hashlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import metrics
from app.core.http import ProviderAuthError
from app.db.models import (
    ChatConnection,
    ChatGroup,
    ConnectionStatus,
    OncallConnection,
    RuleStatus,
    RunStatus,
    RunTrigger,
    SyncRule,
    SyncRun,
)
from app.domain.errors import ChatProviderError
from app.domain.interfaces import ChatProvider
from app.domain.registry import get_chat_provider
from app.domain.types import Announcement
from app.services import chat_connections, sync_rules, templating
from app.services.sync_rules import RuleEvaluation
from app.services.templating import MessageContext

log = structlog.get_logger(__name__)

#: Flag the rule in the UI once failures stop looking like a blip.
CIRCUIT_OPEN_AFTER = 5
FAILURE_BACKOFF_BASE = timedelta(seconds=30)
FAILURE_BACKOFF_CAP = timedelta(minutes=30)
#: Spread simultaneous handoffs so a shared rotation boundary does not stampede.
MAX_JITTER_SECONDS = 30
#: Run history is an audit trail, not an archive — keep it from growing unbounded.
MAX_RUNS_PER_RULE = 100


@dataclass(slots=True)
class ReconcileResult:
    status: RunStatus
    rule_status: RuleStatus
    #: The on-call people changed. This, not membership, is what announcing keys off.
    people_changed: bool = False
    #: Membership disagreed with the desired set without the people changing.
    drift_repaired: bool = False
    wrote_members: list[str] | None = None
    previous_members: list[str] | None = None
    announced: bool = False
    next_run_at: datetime | None = None
    actions: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    error: str | None = None
    #: When the shift in force began, for the handoff-lag measurement.
    shift_start: datetime | None = None


def _lock_key(rule_id: uuid.UUID) -> int:
    """A stable signed 64-bit key for pg_advisory_xact_lock."""
    digest = hashlib.blake2b(rule_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _members_hash(member_ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(member_ids)).encode()).hexdigest()


def _previous_members(rule: SyncRule) -> list[str] | None:
    if not rule.current_members:
        return None
    stored = rule.current_members.get("chat_user_ids")
    return list(stored) if isinstance(stored, list) else None


def _backoff(failures: int) -> timedelta:
    delay: timedelta = FAILURE_BACKOFF_BASE * (2 ** max(0, failures - 1))
    return min(delay, FAILURE_BACKOFF_CAP)


def _message_context(
    *,
    rule: SyncRule,
    evaluation: RuleEvaluation,
    handle: str | None,
    incoming: list[str],
    outgoing: list[str],
    provider: ChatProvider,
) -> MessageContext:
    """Build the template context.

    Mention syntax comes from the provider, not from here: only the adapter knows
    what actually notifies a person on its platform.
    """
    by_id = {member.chat_user_id: member for member in evaluation.resolved}
    incoming_names = [
        by_id[member].provider_user.name if member in by_id else member for member in incoming
    ]
    return MessageContext(
        schedule_name=evaluation.schedule_name,
        rule_name=rule.name,
        handle=handle,
        oncall_mention=" and ".join(provider.format_mention(m) for m in incoming),
        oncall_name=" and ".join(incoming_names) or "nobody",
        previous_mention=" and ".join(provider.format_mention(m) for m in outgoing),
        previous_name=" and ".join(outgoing),
        shift_start=templating.format_time(evaluation.shift_start),
        shift_end=templating.format_time(evaluation.next_change_at),
    )


async def _prune_old_runs(db: AsyncSession, rule_id: uuid.UUID) -> None:
    """Delete everything past the MAX_RUNS_PER_RULE most recent runs for this rule."""
    stale_ids = (
        select(SyncRun.id)
        .where(SyncRun.rule_id == rule_id)
        .order_by(SyncRun.started_at.desc())
        .offset(MAX_RUNS_PER_RULE)
    )
    await db.execute(delete(SyncRun).where(SyncRun.id.in_(stale_ids)))


async def reconcile(
    db: AsyncSession, rule: SyncRule, *, trigger: RunTrigger, at: datetime | None = None
) -> SyncRun:
    """Bring one rule's chat group in line with its schedule, and record the run."""
    started = at or datetime.now(UTC)

    # Serialize per rule. Two runs at once — a predicted handoff landing on top of
    # a manual sync — would race on read-then-write of the group membership.
    await db.execute(select(func.pg_advisory_xact_lock(_lock_key(rule.id))))

    result = await _run(db, rule, trigger=trigger, started=started)
    finished = datetime.now(UTC)
    _record_metrics(rule, result, trigger=trigger, at=finished)

    rule.next_run_at = result.next_run_at
    rule.status = result.rule_status
    if result.status is RunStatus.FAILED:
        rule.consecutive_failures += 1
        rule.last_error = result.error
    elif result.status is not RunStatus.SKIPPED:
        rule.consecutive_failures = 0
        rule.last_error = "; ".join(result.problems) or None
        rule.last_synced_at = finished
        if result.wrote_members is not None or result.status is RunStatus.SUCCESS:
            members = result.wrote_members if result.wrote_members is not None else []
            rule.current_members = {"chat_user_ids": members}
            rule.state_hash = _members_hash(members)

    if rule.consecutive_failures >= CIRCUIT_OPEN_AFTER:
        rule.status = RuleStatus.FAILING

    run = SyncRun(
        org_id=rule.org_id,
        rule_id=rule.id,
        trigger=trigger,
        status=result.status,
        started_at=started,
        finished_at=finished,
        duration_ms=int((finished - started).total_seconds() * 1000),
        previous_members=result.previous_members,
        new_members=result.wrote_members,
        actions=result.actions,
        problems=result.problems,
        error=result.error,
    )
    db.add(run)
    await _prune_old_runs(db, rule.id)
    await db.commit()

    log.info(
        "reconcile.done",
        rule_id=str(rule.id),
        run_id=str(run.id),
        org_id=str(rule.org_id),
        trigger=trigger.value,
        status=result.status.value,
        people_changed=result.people_changed,
        drift_repaired=result.drift_repaired,
        announced=result.announced,
    )
    return run


async def _run(
    db: AsyncSession, rule: SyncRule, *, trigger: RunTrigger, started: datetime
) -> ReconcileResult:
    interval = timedelta(seconds=get_settings().reconcile_interval_seconds)
    previous = _previous_members(rule)

    if not rule.enabled:
        return ReconcileResult(
            status=RunStatus.SKIPPED,
            rule_status=rule.status,
            next_run_at=None,  # a paused rule is not scheduled at all
            actions=["Rule is paused"],
        )

    chat_connection = await db.get(ChatConnection, rule.chat_connection_id)
    oncall_connection = await db.get(OncallConnection, rule.oncall_connection_id)
    if chat_connection is None or oncall_connection is None:
        return _failed(rule, previous, "A connection this rule uses no longer exists", started)

    for connection in (chat_connection, oncall_connection):
        if connection.status is ConnectionStatus.NEEDS_REAUTH:
            # Retrying a dead token just burns rate limit and hides the real fix.
            return ReconcileResult(
                status=RunStatus.SKIPPED,
                rule_status=RuleStatus.DEGRADED,
                previous_members=previous,
                next_run_at=started + interval,
                problems=["A connection needs to be reconnected"],
            )

    try:
        evaluation = await sync_rules.evaluate(db, rule, at=started)
    except ProviderAuthError as exc:
        oncall_connection.status = ConnectionStatus.NEEDS_REAUTH
        oncall_connection.last_error = str(exc)[:500]
        return _failed(rule, previous, f"On-call provider rejected our credentials: {exc}", started)
    except Exception as exc:
        return _failed(rule, previous, str(exc), started)

    # The window fetch already told us when the next shift boundary is, so wake up
    # exactly then instead of polling. The interval is the safety net for
    # retroactive overrides, schedule edits and manual drift.
    scheduled_next = _next_wakeup(evaluation.next_change_at, started, interval)

    result = ReconcileResult(
        status=RunStatus.SUCCESS,
        rule_status=RuleStatus.HEALTHY,
        previous_members=previous,
        next_run_at=scheduled_next,
        problems=list(evaluation.problems),
    )

    if not evaluation.desired_member_ids:
        result.status = RunStatus.DEGRADED
        result.rule_status = RuleStatus.DEGRADED
        result.actions.append("Left the group unchanged: nobody resolved to a chat account")
        # Announce the problem once, on the transition, rather than every interval.
        if rule.status is not RuleStatus.DEGRADED:
            await _try_alert(db, rule, chat_connection, evaluation.problems, result)
        return result

    desired = evaluation.desired_member_ids
    try:
        credentials = await chat_connections.credentials_for(db, chat_connection)
        provider = get_chat_provider(chat_connection.kind)
        actual = await provider.get_group_members(credentials, rule.group_external_id)

        people_changed = previous is None or set(previous) != set(desired)
        membership_differs = set(actual) != set(desired)
        result.people_changed = people_changed
        result.drift_repaired = membership_differs and not people_changed
        result.shift_start = evaluation.shift_start

        if membership_differs:
            await provider.set_group_members(credentials, rule.group_external_id, desired)
            result.wrote_members = desired
            result.actions.append(
                "Repaired manual drift" if result.drift_repaired else "Updated group membership"
            )
        else:
            result.wrote_members = desired
            result.actions.append("Group already correct")

        # Only a genuine change of who is on call earns a message. Repairing a
        # hand-edited group must not post a phantom handoff.
        if people_changed and rule.notify_on_change and rule.notify_channel_external_id:
            outgoing = sorted(set(previous or []) - set(desired))
            handle = await _handle_for(db, rule)
            text, template_problem = templating.safe_render(
                rule.message_template,
                _message_context(
                    rule=rule,
                    evaluation=evaluation,
                    handle=handle,
                    incoming=desired,
                    outgoing=outgoing,
                    provider=provider,
                ),
            )
            if template_problem:
                # The membership update already happened and is what matters; a
                # bad template downgrades the message, not the handoff.
                result.problems.append(template_problem)

            await provider.post_announcement(
                credentials,
                rule.notify_channel_external_id,
                Announcement(
                    text=text,
                    kind="handoff",
                    schedule_name=evaluation.schedule_name,
                    handle=handle,
                    shift_end=evaluation.next_change_at,
                ),
            )
            result.announced = True
            result.actions.append("Announced the handoff")

    except ChatProviderError as exc:
        # Configuration problems, not transient faults. Retrying on a tight loop
        # would not help, so they degrade the rule and surface the fix.
        result.status = RunStatus.DEGRADED
        result.rule_status = RuleStatus.DEGRADED
        result.problems.append(str(exc))
        result.wrote_members = None
        return result
    except ProviderAuthError as exc:
        await chat_connections.mark_revoked(db, chat_connection, str(exc)[:500])
        return _failed(rule, previous, f"Chat workspace rejected our token: {exc}", started)
    except Exception as exc:
        return _failed(rule, previous, str(exc), started)

    if evaluation.problems:
        result.status = RunStatus.DEGRADED
        result.rule_status = RuleStatus.DEGRADED

    return result


def _record_metrics(
    rule: SyncRule, result: ReconcileResult, *, trigger: RunTrigger, at: datetime
) -> None:
    metrics.SYNC_RUNS.labels(status=result.status.value, trigger=trigger.value).inc()

    if result.wrote_members is not None and (result.people_changed or result.drift_repaired):
        reason = "drift_repair" if result.drift_repaired else "handoff"
        metrics.GROUP_WRITES.labels(reason=reason).inc()
    if result.announced:
        metrics.ANNOUNCEMENTS.labels(kind="handoff").inc()

    # Only a scheduled run that actually moved the handle between two known
    # states measures the thing we care about. A manual sync, a first sync, or a
    # drift repair would each report a "lag" that says nothing about how quickly
    # handoffs are picked up, and would quietly poison the SLI.
    if (
        trigger is RunTrigger.SCHEDULED
        and result.people_changed
        and result.previous_members is not None
        and result.shift_start is not None
    ):
        metrics.HANDOFF_LAG.observe(max(0.0, (at - result.shift_start).total_seconds()))


def _next_wakeup(
    next_change_at: datetime | None, started: datetime, interval: timedelta
) -> datetime:
    safety = started + interval
    if next_change_at is None or next_change_at >= safety:
        return safety
    jitter = timedelta(seconds=random.uniform(0, MAX_JITTER_SECONDS))  # noqa: S311
    # A second past the boundary, so the provider has certainly rolled over.
    return next_change_at + timedelta(seconds=1) + jitter


def _failed(
    rule: SyncRule, previous: list[str] | None, message: str, started: datetime
) -> ReconcileResult:
    return ReconcileResult(
        status=RunStatus.FAILED,
        rule_status=rule.status,
        previous_members=previous,
        next_run_at=started + _backoff(rule.consecutive_failures + 1),
        error=message[:1000],
    )


async def _handle_for(db: AsyncSession, rule: SyncRule) -> str | None:
    group = await db.scalar(
        select(ChatGroup).where(
            ChatGroup.chat_connection_id == rule.chat_connection_id,
            ChatGroup.external_id == rule.group_external_id,
        )
    )
    return group.handle if group else None


async def _try_alert(
    db: AsyncSession,
    rule: SyncRule,
    chat_connection: ChatConnection,
    problems: list[str],
    result: ReconcileResult,
) -> None:
    """Tell the channel the handle has stopped tracking. Best effort."""
    if not rule.notify_channel_external_id or not rule.notify_on_change:
        return
    try:
        credentials = await chat_connections.credentials_for(db, chat_connection)
        await get_chat_provider(chat_connection.kind).post_announcement(
            credentials,
            rule.notify_channel_external_id,
            Announcement(
                text=(
                    ":warning: On-call sync could not update "
                    f"*{rule.name}*: {'; '.join(problems)}. The handle is unchanged."
                ),
                kind="problem",
            ),
        )
        result.actions.append("Alerted the channel")
    except Exception as exc:
        # An alert that cannot be delivered must not turn a degraded run into a
        # failed one; the run record already carries the real problem.
        log.warning("reconcile.alert_failed", rule_id=str(rule.id), error=str(exc))
