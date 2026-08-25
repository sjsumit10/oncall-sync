"""Enqueueing reconcile work from the API and webhook processes."""

from typing import Any

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

log = structlog.get_logger(__name__)

RECONCILE_TASK = "reconcile_rule"

_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(str(get_settings().redis_url)))
    return _pool


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue_reconcile(rule_id: Any, org_id: Any, trigger: str) -> None:
    queue = await get_queue()
    await queue.enqueue_job(RECONCILE_TASK, str(rule_id), str(org_id), trigger)
    log.debug("queue.enqueued", rule_id=str(rule_id), trigger=trigger)
