"""Chat workspace installation, and the group and channel pickers."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.v1.schemas import (
    ChatChannelOut,
    ChatConnectionOut,
    ChatGroupOut,
    ChatProviderOut,
    ConnectionHealthOut,
)
from app.config import get_settings
from app.core.deps import CurrentUser, DbSession, RedisClient, require_role
from app.core.errors import BadRequest, NotFound
from app.core.sessions import SESSION_COOKIE, read_session
from app.db.models import MANAGER_ROLES, ChatChannel, ChatConnection, ChatGroup, User
from app.db.repository import OrgScope
from app.db.session import bind_org
from app.domain.registry import CHAT_PROVIDERS, get_chat_provider
from app.providers.chat.slack.provider import UserGroupsUnavailable
from app.services import chat_connections, oauth_state

router = APIRouter(prefix="/chat", tags=["chat workspaces"])

RequireManager = Depends(require_role(*MANAGER_ROLES))


class InstallStartOut(BaseModel):
    install_url: str


def _callback_uri(kind: str) -> str:
    return f"{get_settings().app_base_url}/api/v1/chat/{kind}/callback"


def _install_configured(kind: str) -> bool:
    settings = get_settings()
    if kind == "slack":
        return bool(settings.slack_client_id and settings.slack_client_secret)
    return False


def _to_out(connection: ChatConnection) -> ChatConnectionOut:
    return ChatConnectionOut(
        id=connection.id,
        kind=connection.kind,
        external_team_id=connection.external_team_id,
        team_name=connection.team_name,
        status=connection.status.value,
        scopes=connection.scopes,
        has_user_token=connection.user_token_enc is not None,
        last_verified_at=connection.last_verified_at,
        last_error=connection.last_error,
        groups_synced_at=connection.groups_synced_at,
        created_at=connection.created_at,
    )


@router.get("/providers", response_model=list[ChatProviderOut])
async def list_providers(_: CurrentUser) -> list[ChatProviderOut]:
    return [
        ChatProviderOut(
            kind=kind,
            display_name=provider.display_name,
            install_configured=_install_configured(kind),
        )
        for kind, provider in CHAT_PROVIDERS.items()
    ]


@router.get("/connections", response_model=list[ChatConnectionOut])
async def list_connections(user: CurrentUser, db: DbSession) -> list[ChatConnectionOut]:
    scope = OrgScope(db, user.org_id)
    rows = sorted(await scope.list(ChatConnection), key=lambda c: c.created_at)
    return [_to_out(row) for row in rows]


@router.post("/{kind}/install/start", response_model=InstallStartOut)
async def start_install(
    kind: str, redis: RedisClient, actor: User = RequireManager
) -> InstallStartOut:
    if kind not in CHAT_PROVIDERS:
        raise NotFound(f"Unknown chat provider: {kind}")
    if not _install_configured(kind):
        raise BadRequest(f"This deployment has no {kind} app configured")

    redirect_uri = _callback_uri(kind)
    state = await oauth_state.issue(
        redis,
        org_id=actor.org_id,
        user_id=actor.id,
        kind=kind,
        # Slack's install flow has no PKCE; the field is unused here.
        code_verifier="",
        redirect_uri=redirect_uri,
    )
    return InstallStartOut(
        install_url=get_chat_provider(kind).install_url(state=state, redirect_uri=redirect_uri)
    )


@router.get("/{kind}/callback", include_in_schema=False)
async def finish_install(
    kind: str,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
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

    cookie = request.cookies.get(SESSION_COOKIE)
    session_data = await read_session(redis, cookie) if cookie else None
    if session_data is None or session_data.user_id != stored.user_id:
        return back("error=session_mismatch")

    org_id = uuid.UUID(stored.org_id)
    # Unauthenticated request path, so bind the tenant or RLS refuses the write.
    await bind_org(db, org_id)

    try:
        install = await get_chat_provider(kind).complete_install(
            code=code, redirect_uri=stored.redirect_uri
        )
        await chat_connections.upsert_install(
            db,
            org_id=org_id,
            kind=kind,
            install=install,
            installed_by_user_id=uuid.UUID(stored.user_id),
        )
        await db.commit()
    except Exception:
        return back("error=install_failed")

    return back(f"installed={kind}")


@router.post("/connections/{connection_id}/verify", response_model=ConnectionHealthOut)
async def verify_connection(
    connection_id: uuid.UUID, db: DbSession, actor: User = RequireManager
) -> ConnectionHealthOut:
    connection = await OrgScope(db, actor.org_id).get(ChatConnection, connection_id)
    if connection is None:
        raise NotFound("Workspace not found")
    health = await chat_connections.verify_connection(db, connection)
    return ConnectionHealthOut(ok=health.ok, detail=health.detail)


@router.get("/connections/{connection_id}/groups", response_model=list[ChatGroupOut])
async def list_groups(
    connection_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    refresh: bool = Query(default=False),
) -> list[ChatGroup]:
    scope = OrgScope(db, user.org_id)
    connection = await scope.get(ChatConnection, connection_id)
    if connection is None:
        raise NotFound("Workspace not found")

    if refresh or connection.groups_synced_at is None:
        try:
            return await chat_connections.sync_groups(db, connection)
        except UserGroupsUnavailable as exc:
            raise BadRequest(str(exc)) from exc

    return list(
        await db.scalars(
            scope.select(ChatGroup)
            .where(ChatGroup.chat_connection_id == connection_id)
            .order_by(ChatGroup.handle)
        )
    )


@router.get("/connections/{connection_id}/channels", response_model=list[ChatChannelOut])
async def list_channels(
    connection_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    refresh: bool = Query(default=False),
) -> list[ChatChannel]:
    scope = OrgScope(db, user.org_id)
    connection = await scope.get(ChatConnection, connection_id)
    if connection is None:
        raise NotFound("Workspace not found")

    cached = list(
        await db.scalars(
            scope.select(ChatChannel)
            .where(ChatChannel.chat_connection_id == connection_id)
            .order_by(ChatChannel.name)
        )
    )
    if refresh or not cached:
        return await chat_connections.sync_channels(db, connection)
    return cached


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID, db: DbSession, actor: User = RequireManager
) -> None:
    connection = await OrgScope(db, actor.org_id).get(ChatConnection, connection_id)
    if connection is None:
        raise NotFound("Workspace not found")
    await db.delete(connection)
    await db.commit()
