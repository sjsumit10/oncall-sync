"""Connection lifecycle for on-call providers.

Owns credential encryption, OAuth token refresh and the cached schedule list, so
provider adapters stay stateless and the API layer never touches ciphertext.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.errors import BadRequest, Conflict
from app.core.http import ProviderAuthError
from app.db.models import ConnectionStatus, OncallConnection, OncallSchedule
from app.domain.registry import get_oncall_oauth, get_oncall_provider
from app.domain.types import AuthMode, Credentials, OAuthTokens, ProviderHealth

log = structlog.get_logger(__name__)

#: Refresh this far ahead of expiry so a long reconcile cannot straddle it.
REFRESH_MARGIN = timedelta(minutes=5)


async def _credentials_from(
    db: AsyncSession, connection: OncallConnection, token: str
) -> Credentials:
    return Credentials(org_id=connection.org_id, auth_mode=connection.auth_mode, token=token)


def _needs_refresh(connection: OncallConnection) -> bool:
    if connection.auth_mode is not AuthMode.OAUTH or connection.refresh_token_enc is None:
        return False
    if connection.token_expires_at is None:
        return False
    return connection.token_expires_at <= datetime.now(UTC) + REFRESH_MARGIN


async def _apply_tokens(
    db: AsyncSession, connection: OncallConnection, tokens: OAuthTokens
) -> None:
    connection.credentials_enc = await crypto.encrypt(db, connection.org_id, tokens.access_token)
    if tokens.refresh_token:
        # PagerDuty rotates refresh tokens, so the new one must replace the old.
        connection.refresh_token_enc = await crypto.encrypt(
            db, connection.org_id, tokens.refresh_token
        )
    connection.token_expires_at = tokens.expires_at
    if tokens.scope:
        connection.scopes = tokens.scope
    connection.status = ConnectionStatus.ACTIVE
    connection.last_error = None


async def credentials_for(db: AsyncSession, connection: OncallConnection) -> Credentials:
    """Decrypt this connection's credential, refreshing an expiring token first."""
    if _needs_refresh(connection):
        assert connection.refresh_token_enc is not None
        refresh_token = await crypto.decrypt(db, connection.org_id, connection.refresh_token_enc)
        try:
            tokens = await get_oncall_oauth(connection.kind).refresh(refresh_token=refresh_token)
        except ProviderAuthError as exc:
            connection.status = ConnectionStatus.NEEDS_REAUTH
            connection.last_error = "Refresh token rejected; reconnect required"
            await db.commit()
            log.warning("oncall.refresh_failed", connection_id=str(connection.id), error=str(exc))
            raise
        await _apply_tokens(db, connection, tokens)
        await db.commit()
        log.info("oncall.token_refreshed", connection_id=str(connection.id))
        return await _credentials_from(db, connection, tokens.access_token)

    token = await crypto.decrypt(db, connection.org_id, connection.credentials_enc)
    return await _credentials_from(db, connection, token)


async def _verify_or_reject(kind: str, credentials: Credentials) -> ProviderHealth:
    try:
        return await get_oncall_provider(kind).verify(credentials)
    except ProviderAuthError as exc:
        raise BadRequest(f"{kind} rejected those credentials: {exc}") from exc


async def create_from_api_key(
    db: AsyncSession, *, org_id: uuid.UUID, kind: str, api_key: str, display_name: str
) -> OncallConnection:
    """Verify before storing: a credential that never worked should not be saved."""
    provider = get_oncall_provider(kind)
    if AuthMode.API_KEY not in provider.auth_modes:
        raise BadRequest(f"{provider.display_name} does not accept API keys")

    health = await _verify_or_reject(
        kind, Credentials(org_id=org_id, auth_mode=AuthMode.API_KEY, token=api_key)
    )

    connection = OncallConnection(
        org_id=org_id,
        kind=kind,
        auth_mode=AuthMode.API_KEY,
        display_name=display_name.strip() or provider.display_name,
        credentials_enc=await crypto.encrypt(db, org_id, api_key),
        status=ConnectionStatus.ACTIVE,
        last_verified_at=datetime.now(UTC),
        external_account_id=health.account_label,
    )
    db.add(connection)
    await db.flush()
    return connection


async def create_from_oauth(
    db: AsyncSession, *, org_id: uuid.UUID, kind: str, tokens: OAuthTokens, display_name: str
) -> OncallConnection:
    provider = get_oncall_provider(kind)
    existing = await db.scalar(
        select(OncallConnection).where(
            OncallConnection.org_id == org_id,
            OncallConnection.kind == kind,
            OncallConnection.auth_mode == AuthMode.OAUTH,
        )
    )

    # Reconnecting replaces the credential in place so existing sync rules keep
    # pointing at the same connection id.
    connection = existing or OncallConnection(
        org_id=org_id,
        kind=kind,
        auth_mode=AuthMode.OAUTH,
        display_name=display_name.strip() or provider.display_name,
        credentials_enc=b"",
    )
    await _apply_tokens(db, connection, tokens)
    connection.last_verified_at = datetime.now(UTC)
    if existing is None:
        db.add(connection)
    await db.flush()
    return connection


async def verify_connection(db: AsyncSession, connection: OncallConnection) -> ProviderHealth:
    try:
        credentials = await credentials_for(db, connection)
        health = await get_oncall_provider(connection.kind).verify(credentials)
    except ProviderAuthError as exc:
        connection.status = ConnectionStatus.NEEDS_REAUTH
        connection.last_error = str(exc)[:500]
        await db.commit()
        return ProviderHealth(ok=False, detail="Credentials rejected; reconnect required")
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


async def sync_schedules(db: AsyncSession, connection: OncallConnection) -> list[OncallSchedule]:
    """Refresh the cached schedule list, adding, updating and pruning."""
    credentials = await credentials_for(db, connection)
    fetched = await get_oncall_provider(connection.kind).list_schedules(credentials)

    existing = {
        row.external_id: row
        for row in await db.scalars(
            select(OncallSchedule).where(OncallSchedule.connection_id == connection.id)
        )
    }
    now = datetime.now(UTC)
    seen: set[str] = set()

    for ref in fetched:
        seen.add(ref.external_id)
        row = existing.get(ref.external_id)
        if row is None:
            row = OncallSchedule(
                org_id=connection.org_id,
                connection_id=connection.id,
                external_id=ref.external_id,
            )
            db.add(row)
        row.name = ref.name
        row.timezone = ref.timezone
        row.description = ref.description
        row.html_url = ref.html_url
        row.synced_at = now

    # A schedule deleted in PagerDuty should stop appearing in pickers. Sync rules
    # referencing it are handled when the rule next reconciles, not here.
    for external_id, row in existing.items():
        if external_id not in seen:
            await db.delete(row)

    connection.schedules_synced_at = now
    await db.commit()

    return list(
        await db.scalars(
            select(OncallSchedule)
            .where(OncallSchedule.connection_id == connection.id)
            .order_by(OncallSchedule.name)
        )
    )


async def assert_unique_api_key_connection(db: AsyncSession, org_id: uuid.UUID, kind: str) -> None:
    existing = await db.scalar(
        select(OncallConnection.id).where(
            OncallConnection.org_id == org_id,
            OncallConnection.kind == kind,
            OncallConnection.auth_mode == AuthMode.API_KEY,
        )
    )
    if existing is not None:
        raise Conflict(f"An API key connection for {kind} already exists")
