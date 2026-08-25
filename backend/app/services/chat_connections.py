"""Chat workspace lifecycle: install, verification, and the cached pickers."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.http import ProviderAuthError
from app.db.models import ChatChannel, ChatConnection, ChatGroup, ConnectionStatus
from app.domain.errors import GroupsUnavailable
from app.domain.registry import get_chat_provider
from app.domain.types import ChatCredentials, ChatInstall, ProviderHealth

log = structlog.get_logger(__name__)


async def credentials_for(db: AsyncSession, connection: ChatConnection) -> ChatCredentials:
    """Decrypt both tokens. Slack bot tokens do not expire, so there is no refresh."""
    bot_token = await crypto.decrypt(db, connection.org_id, connection.bot_token_enc)
    user_token = (
        await crypto.decrypt(db, connection.org_id, connection.user_token_enc)
        if connection.user_token_enc
        else None
    )
    return ChatCredentials(org_id=connection.org_id, bot_token=bot_token, user_token=user_token)


async def upsert_install(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: str,
    install: ChatInstall,
    installed_by_user_id: uuid.UUID | None,
) -> ChatConnection:
    """Store a completed install, replacing a prior one for the same workspace.

    Reinstalling keeps the connection id so sync rules pointing at it survive —
    which is exactly what a reconnect after a revoked token needs to do.
    """
    existing = await db.scalar(
        select(ChatConnection).where(
            ChatConnection.org_id == org_id,
            ChatConnection.kind == kind,
            ChatConnection.external_team_id == install.external_team_id,
        )
    )
    connection = existing or ChatConnection(
        org_id=org_id,
        kind=kind,
        external_team_id=install.external_team_id,
        bot_token_enc=b"",
    )

    connection.team_name = install.team_name
    connection.bot_token_enc = await crypto.encrypt(db, org_id, install.bot_token)
    connection.bot_user_id = install.bot_user_id
    # A reinstall without user scopes must not silently drop a token we still need.
    if install.user_token:
        connection.user_token_enc = await crypto.encrypt(db, org_id, install.user_token)
        connection.installing_user_external_id = install.installing_user_external_id
        connection.user_scopes = install.user_scopes
    connection.scopes = install.scopes
    connection.installed_by_user_id = installed_by_user_id
    connection.status = ConnectionStatus.ACTIVE
    connection.last_error = None
    connection.last_verified_at = datetime.now(UTC)

    if existing is None:
        db.add(connection)
    await db.flush()
    return connection


async def verify_connection(db: AsyncSession, connection: ChatConnection) -> ProviderHealth:
    try:
        credentials = await credentials_for(db, connection)
        health = await get_chat_provider(connection.kind).verify(credentials)
    except ProviderAuthError as exc:
        await mark_revoked(db, connection, str(exc)[:500])
        return ProviderHealth(ok=False, detail="Slack rejected the token; reinstall required")
    except Exception as exc:
        connection.status = ConnectionStatus.ERROR
        connection.last_error = str(exc)[:500]
        await db.commit()
        return ProviderHealth(ok=False, detail=f"Verification failed: {exc}")

    connection.status = ConnectionStatus.ACTIVE
    connection.last_verified_at = datetime.now(UTC)
    connection.last_error = None
    await db.commit()
    return health


async def mark_revoked(db: AsyncSession, connection: ChatConnection, reason: str) -> None:
    """Flip a workspace to needs-reauth rather than retrying a dead token forever."""
    connection.status = ConnectionStatus.NEEDS_REAUTH
    connection.last_error = reason
    await db.commit()
    log.warning("chat.connection_revoked", connection_id=str(connection.id), kind=connection.kind)


async def sync_groups(db: AsyncSession, connection: ChatConnection) -> list[ChatGroup]:
    credentials = await credentials_for(db, connection)
    try:
        fetched = await get_chat_provider(connection.kind).list_groups(credentials)
    except GroupsUnavailable as exc:
        # The core feature is unavailable on this plan. Say so plainly now rather
        # than letting the first sync fail mysteriously later.
        connection.status = ConnectionStatus.ERROR
        connection.last_error = str(exc)
        await db.commit()
        raise

    existing = {
        row.external_id: row
        for row in await db.scalars(
            select(ChatGroup).where(ChatGroup.chat_connection_id == connection.id)
        )
    }
    now = datetime.now(UTC)
    seen = set()

    for ref in fetched:
        seen.add(ref.external_id)
        row = existing.get(ref.external_id)
        if row is None:
            row = ChatGroup(
                org_id=connection.org_id,
                chat_connection_id=connection.id,
                external_id=ref.external_id,
            )
            db.add(row)
        row.handle = ref.handle
        row.name = ref.name
        row.is_active = ref.is_active
        row.synced_at = now

    for external_id, row in existing.items():
        if external_id not in seen:
            await db.delete(row)

    connection.groups_synced_at = now
    await db.commit()

    return list(
        await db.scalars(
            select(ChatGroup)
            .where(ChatGroup.chat_connection_id == connection.id)
            .order_by(ChatGroup.handle)
        )
    )


async def sync_channels(db: AsyncSession, connection: ChatConnection) -> list[ChatChannel]:
    credentials = await credentials_for(db, connection)
    fetched = await get_chat_provider(connection.kind).list_channels(credentials)

    existing = {
        row.external_id: row
        for row in await db.scalars(
            select(ChatChannel).where(ChatChannel.chat_connection_id == connection.id)
        )
    }
    now = datetime.now(UTC)
    seen = set()

    for ref in fetched:
        seen.add(ref.external_id)
        row = existing.get(ref.external_id)
        if row is None:
            row = ChatChannel(
                org_id=connection.org_id,
                chat_connection_id=connection.id,
                external_id=ref.external_id,
            )
            db.add(row)
        row.name = ref.name
        row.is_private = ref.is_private
        row.bot_is_member = ref.is_member
        row.synced_at = now

    for external_id, row in existing.items():
        if external_id not in seen:
            await db.delete(row)

    await db.commit()

    return list(
        await db.scalars(
            select(ChatChannel)
            .where(ChatChannel.chat_connection_id == connection.id)
            .order_by(ChatChannel.name)
        )
    )


async def find_by_team_id(
    db: AsyncSession, *, kind: str, external_team_id: str
) -> list[ChatConnection]:
    """Look up installs by workspace id.

    Used by the events endpoint, which is unauthenticated and knows only the
    team id — so this deliberately spans tenants and the caller must bind the
    org before writing.
    """
    return list(
        await db.scalars(
            select(ChatConnection).where(
                ChatConnection.kind == kind,
                ChatConnection.external_team_id == external_team_id,
            )
        )
    )
