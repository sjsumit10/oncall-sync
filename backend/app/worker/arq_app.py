"""ARQ worker entrypoint."""

from datetime import timedelta
from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings
from prometheus_client import start_http_server

from app.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis
from app.db.session import dispose_admin_engine
from app.worker import beat, queue
from app.worker.tasks import reconcile_rule, tick

settings = get_settings()
log = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    # Better to refuse to start than to run a scheduler that can see nothing.
    await beat.assert_scheduler_can_see_rules()

    # Nearly every reconcile happens here rather than in the API, so without its
    # own scrape endpoint the handoff-lag SLI would never be collected.
    try:
        start_http_server(settings.worker_metrics_port)
    except OSError as exc:
        log.warning(
            "worker.metrics_port_unavailable", port=settings.worker_metrics_port, error=str(exc)
        )

    log.info(
        "worker.started",
        reconcile_interval=settings.reconcile_interval_seconds,
        metrics_port=settings.worker_metrics_port,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await queue.close_queue()
    await close_redis()
    await dispose_admin_engine()


def _beat_seconds() -> set[int]:
    """Seconds of each minute on which the beat fires."""
    step = max(1, min(60, settings.beat_interval_seconds))
    return set(range(0, 60, step))


class WorkerSettings:
    functions: ClassVar[list[Any]] = [reconcile_rule]
    cron_jobs: ClassVar[list[Any]] = [
        cron(tick, second=_beat_seconds(), run_at_startup=True, max_tries=1),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    max_jobs = 20
    job_timeout = timedelta(minutes=5)
