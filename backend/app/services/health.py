"""Fleet-wide counts, for the metrics endpoint and the overview page.

The rule and connection gauges are read at scrape time rather than pushed, so a
restarted process reports the truth immediately instead of zeros until something
happens to move a counter.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.db.models import (
    ChatConnection,
    ConnectionStatus,
    OncallConnection,
    RuleStatus,
    SyncRule,
)
from app.db.repository import OrgScope
from app.db.session import get_admin_engine


@dataclass(slots=True)
class OrgHealth:
    rules_total: int = 0
    rules_by_status: dict[str, int] = field(default_factory=dict)
    connections_needing_attention: int = 0
    rules_paused: int = 0


async def org_health(db: AsyncSession, scope: OrgScope) -> OrgHealth:
    rows = await db.execute(
        scope.select(SyncRule)
        .with_only_columns(SyncRule.status, func.count(SyncRule.id))
        .group_by(SyncRule.status)
    )
    by_status = {status.value: count for status, count in rows.all()}

    paused = await db.scalar(
        scope.select(SyncRule)
        .with_only_columns(func.count(SyncRule.id))
        .where(SyncRule.enabled.is_(False))
    )

    unhealthy = 0
    for model in (OncallConnection, ChatConnection):
        count = await db.scalar(
            scope.select(model)
            .with_only_columns(func.count(model.id))
            .where(model.status != ConnectionStatus.ACTIVE)
        )
        unhealthy += count or 0

    return OrgHealth(
        rules_total=sum(by_status.values()),
        rules_by_status=by_status,
        connections_needing_attention=unhealthy,
        rules_paused=paused or 0,
    )


async def refresh_gauges() -> None:
    """Repopulate the fleet gauges from the database.

    Spans tenants — these are operator metrics, not per-customer data — so it uses
    the privileged connection, the same way the scheduler's claim does.
    """
    async with get_admin_engine().connect() as conn:
        rule_rows = (
            await conn.execute(text("SELECT status, count(*) FROM sync_rules GROUP BY status"))
        ).all()
        connection_rows = (
            await conn.execute(
                text("""
                SELECT kind, status, count(*) FROM oncall_connections GROUP BY kind, status
                UNION ALL
                SELECT kind, status, count(*) FROM chat_connections GROUP BY kind, status
                """)
            )
        ).all()

    # Clear first so a status that dropped to zero stops being reported at its
    # last non-zero value.
    metrics.RULES.clear()
    for status in RuleStatus:
        metrics.RULES.labels(status=status.value).set(0)
    for status_value, count in rule_rows:
        metrics.RULES.labels(status=str(status_value)).set(count)

    metrics.CONNECTIONS.clear()
    for kind, status_value, count in connection_rows:
        metrics.CONNECTIONS.labels(kind=str(kind), status=str(status_value)).set(count)
