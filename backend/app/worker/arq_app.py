"""ARQ worker.

Postgres is the scheduler of record: every sync rule carries ``next_run_at``.
``beat`` claims due rules with SELECT ... FOR UPDATE SKIP LOCKED and enqueues a
reconcile job for each. Redis only carries the queue, so losing it costs at most
one beat tick rather than silently dropping every future handoff.
"""

from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings

from app.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
log = structlog.get_logger(__name__)


async def beat(ctx: dict[str, Any]) -> None:
    """Claim rules whose next_run_at has passed and enqueue reconciles. (M5)"""
    log.debug("beat.tick")


async def reconcile_rule(ctx: dict[str, Any], rule_id: str, trigger: str) -> None:
    """Run the sync engine for one rule. (M5)"""
    log.info("reconcile.requested", rule_id=rule_id, trigger=trigger)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    log.info("worker.started")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [reconcile_rule]
    cron_jobs: ClassVar[list[Any]] = []
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    max_jobs = 20
