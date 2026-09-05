"""On-call provider connections: OAuth, API keys and the cached schedule list."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.v1.schemas import (
    ConnectionHealthOut,
    OncallConnectionOut,
    OncallProviderOut,
    OncallScheduleOut,
)
from app.config import get_settings
from app.core.deps import CurrentUser, DbSession, RedisClient, require_role
from app.core.errors import BadRequest, NotFound
from app.core.oauth import generate_pkce_pair
from app.core.sessions import SESSION_COOKIE, read_session
from app.db.models import MANAGER_ROLES, OncallConnection, OncallSchedule, User
from app.db.repository import OrgScope
from app.db.session import bind_org
from app.domain.registry import ONCALL_OAUTH_FLOWS, ONCALL_PROVIDERS, get_oncall_oauth
from app.services import oauth_state, oncall_connections

router = APIRouter(prefix="/oncall", tags=["on-call providers"])

RequireManager = Depends(require_role(*MANAGER_ROLES))


class ApiKeyConnectionIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    api_key: str = Field(min_length=8, max_length=512)
    display_name: str = Field(default="", max_length=160)


class OAuthStartOut(BaseModel):
    authorize_url: str


def _callback_uri(kind: str) -> str:
    base = get_settings().oauth_public_base_url
    return f"{base}/api/v1/oncall/connections/{kind}/oauth/callback"


def _oauth_configured(kind: str) -> bool:
    """OAuth is only offered when the deployment actually has app credentials."""
    settings = get_settings()
    if kind == "pagerduty":
        return bool(settings.pagerduty_client_id and settings.pagerduty_client_secret)
    return False


@router.get("/providers", response_model=list[OncallProviderOut])
async def list_providers(_: CurrentUser) -> list[OncallProviderOut]:
    return [
        OncallProviderOut(
            kind=provider.kind,
            display_name=provider.display_name,
            auth_modes=[mode.value for mode in provider.auth_modes],
            supports_oauth=kind in ONCALL_OAUTH_FLOWS,
            oauth_configured=_oauth_configured(kind),
        )
        for kind, provider in ONCALL_PROVIDERS.items()
    ]


@router.get("/connections", response_model=list[OncallConnectionOut])
async def list_connections(user: CurrentUser, db: DbSession) -> list[OncallConnection]:
    scope = OrgScope(db, user.org_id)
    return sorted(await scope.list(OncallConnection), key=lambda c: c.created_at)


@router.post(
    "/connections", response_model=OncallConnectionOut, status_code=status.HTTP_201_CREATED
)
async def create_api_key_connection(
    payload: ApiKeyConnectionIn, db: DbSession, actor: User = RequireManager
) -> OncallConnection:
    if payload.kind not in ONCALL_PROVIDERS:
        raise NotFound(f"Unknown provider: {payload.kind}")

    await oncall_connections.assert_unique_api_key_connection(db, actor.org_id, payload.kind)
    connection = await oncall_connections.create_from_api_key(
        db,
        org_id=actor.org_id,
        kind=payload.kind,
        api_key=payload.api_key,
        display_name=payload.display_name,
    )
    await db.commit()
    return connection


@router.post("/connections/{kind}/oauth/start", response_model=OAuthStartOut)
async def start_oauth(kind: str, redis: RedisClient, actor: User = RequireManager) -> OAuthStartOut:
    if kind not in ONCALL_OAUTH_FLOWS:
        raise NotFound(f"{kind} does not support OAuth")
    if not _oauth_configured(kind):
        raise BadRequest(f"This deployment has no {kind} OAuth app configured")

    verifier, challenge = generate_pkce_pair()
    redirect_uri = _callback_uri(kind)
    state = await oauth_state.issue(
        redis,
        org_id=actor.org_id,
        user_id=actor.id,
        kind=kind,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
    )
    url = get_oncall_oauth(kind).authorize_url(
        state=state, redirect_uri=redirect_uri, code_challenge=challenge
    )
    return OAuthStartOut(authorize_url=url)


@router.get("/connections/{kind}/oauth/callback", include_in_schema=False)
async def finish_oauth(
    kind: str,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Redirect leg of the OAuth flow.

    Reached by browser navigation, so there is no session header to check — the
    single-use state token issued at /start is what proves this callback belongs
    to the browser that began the flow.
    """
    web = get_settings().web_base_url

    def back(outcome: str) -> RedirectResponse:
        return RedirectResponse(f"{web}/connections?{outcome}", status_code=302)

    if error:
        return back(f"error={error}")
    if not code or not state:
        return back("error=missing_code")

    stored = await oauth_state.consume(redis, state)
    if stored is None or stored.kind != kind:
        return back("error=invalid_state")

    # The state was minted for one session. Binding the callback to that same
    # session stops a stolen or replayed callback URL from attaching a connection
    # to somebody else's organization.
    cookie = request.cookies.get(SESSION_COOKIE)
    session_data = await read_session(redis, cookie) if cookie else None
    if session_data is None or session_data.user_id != stored.user_id:
        return back("error=session_mismatch")

    org_id = uuid.UUID(stored.org_id)
    # No authenticated dependency ran on this request, so bind the tenant
    # explicitly or RLS will refuse to store the connection.
    await bind_org(db, org_id)

    try:
        tokens = await get_oncall_oauth(kind).exchange_code(
            code=code, redirect_uri=stored.redirect_uri, code_verifier=stored.code_verifier
        )
        connection = await oncall_connections.create_from_oauth(
            db,
            org_id=org_id,
            kind=kind,
            tokens=tokens,
            display_name=ONCALL_PROVIDERS[kind].display_name,
        )
        await db.commit()
    except Exception:
        return back("error=exchange_failed")

    return back(f"connected={connection.kind}")


@router.post("/connections/{connection_id}/verify", response_model=ConnectionHealthOut)
async def verify_connection(
    connection_id: uuid.UUID, db: DbSession, actor: User = RequireManager
) -> ConnectionHealthOut:
    connection = await OrgScope(db, actor.org_id).get(OncallConnection, connection_id)
    if connection is None:
        raise NotFound("Connection not found")

    health = await oncall_connections.verify_connection(db, connection)
    return ConnectionHealthOut(ok=health.ok, detail=health.detail)


@router.get("/connections/{connection_id}/schedules", response_model=list[OncallScheduleOut])
async def list_schedules(
    connection_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    refresh: bool = Query(default=False, description="Re-fetch from the provider first"),
) -> list[OncallSchedule]:
    scope = OrgScope(db, user.org_id)
    connection = await scope.get(OncallConnection, connection_id)
    if connection is None:
        raise NotFound("Connection not found")

    # Fetch on first use so a freshly connected account is not an empty picker.
    if refresh or connection.schedules_synced_at is None:
        return await oncall_connections.sync_schedules(db, connection)

    return list(
        await db.scalars(
            scope.select(OncallSchedule)
            .where(OncallSchedule.connection_id == connection_id)
            .order_by(OncallSchedule.name)
        )
    )


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID, db: DbSession, actor: User = RequireManager
) -> None:
    connection = await OrgScope(db, actor.org_id).get(OncallConnection, connection_id)
    if connection is None:
        raise NotFound("Connection not found")
    await db.delete(connection)
    await db.commit()
