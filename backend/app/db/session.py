"""Async engine, session factory, and the tenant guard.

Row-level security keys off the ``app.current_org_id`` Postgres setting. Rather
than remembering to set it at every call site, an ``after_begin`` listener applies
the current request's org to *every* transaction the session opens — including one
started after an intermediate commit, which is exactly the case a manual
``SET LOCAL`` would silently miss.
"""

import uuid
from collections.abc import AsyncIterator
from contextvars import ContextVar, Token

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    str(_settings.database_url),
    pool_pre_ping=True,
    echo=_settings.debug,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

#: Org of the authenticated caller. Unset for unauthenticated and worker contexts.
current_org_id: ContextVar[uuid.UUID | None] = ContextVar("current_org_id", default=None)

ORG_GUC = "app.current_org_id"


def set_current_org(org_id: uuid.UUID | None) -> Token[uuid.UUID | None]:
    return current_org_id.set(org_id)


@event.listens_for(Session, "after_begin")
def _apply_org_guc(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    org_id = current_org_id.get()
    # is_local=true scopes the setting to this transaction, so a pooled connection
    # never carries one tenant's org into the next request that borrows it.
    connection.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": ORG_GUC, "value": str(org_id) if org_id else ""},
    )


async def bind_org(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Bind a tenant to this request and to the transaction already in flight.

    The contextvar covers every transaction the session opens from here on; the
    explicit set_config covers the one that is already open. Any code path that
    writes tenant data without going through an authenticated dependency — the
    OAuth callback, invite acceptance, background jobs — must call this or RLS
    will refuse the write.
    """
    set_current_org(org_id)
    await session.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": ORG_GUC, "value": str(org_id)},
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to the caller's org."""
    async with SessionLocal() as session:
        yield session
