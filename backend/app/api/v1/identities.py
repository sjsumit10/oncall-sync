"""Matching on-call people to chat accounts, and fixing it by hand when needed."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.v1.schemas import DirectoryEntryOut, IdentityLinkOut, ProviderUserOut
from app.core.deps import CurrentUser, DbSession, require_role
from app.core.errors import BadRequest, NotFound
from app.db.models import MANAGER_ROLES, ChatConnection, IdentityLink, OncallConnection, User
from app.db.repository import OrgScope
from app.domain.registry import get_chat_provider, get_oncall_provider
from app.services import chat_connections, identity_resolver, oncall_connections

router = APIRouter(prefix="/identities", tags=["identities"])

RequireManager = Depends(require_role(*MANAGER_ROLES))


class LinkIn(BaseModel):
    oncall_connection_id: uuid.UUID
    chat_connection_id: uuid.UUID
    provider_user_id: str = Field(min_length=1, max_length=120)
    chat_user_id: str = Field(min_length=1, max_length=120)


@router.get("", response_model=list[DirectoryEntryOut])
async def list_directory(
    oncall_connection_id: uuid.UUID,
    chat_connection_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    unmapped_only: bool = Query(default=False),
) -> list[DirectoryEntryOut]:
    """The on-call provider's people, each with its chat link if one exists.

    Fetched live rather than cached: the directory is read on a rarely-visited
    settings page, and a stale list here would send someone chasing a link that
    already exists.
    """
    scope = OrgScope(db, user.org_id)
    oncall_connection = await scope.get(OncallConnection, oncall_connection_id)
    chat_connection = await scope.get(ChatConnection, chat_connection_id)
    if oncall_connection is None or chat_connection is None:
        raise NotFound("Connection not found")

    credentials = await oncall_connections.credentials_for(db, oncall_connection)
    people = await get_oncall_provider(oncall_connection.kind).list_users(credentials)
    links = await identity_resolver.existing_links(
        db,
        oncall_connection_id=oncall_connection_id,
        chat_connection_id=chat_connection_id,
    )

    entries = [
        DirectoryEntryOut(
            provider_user=ProviderUserOut(
                external_id=person.external_id, name=person.name, email=person.email
            ),
            link=(
                IdentityLinkOut.model_validate(links[person.external_id])
                if person.external_id in links
                else None
            ),
        )
        for person in people
    ]
    if unmapped_only:
        entries = [entry for entry in entries if entry.link is None]
    return sorted(entries, key=lambda entry: entry.provider_user.name.lower())


@router.post("", response_model=IdentityLinkOut, status_code=status.HTTP_201_CREATED)
async def create_link(payload: LinkIn, db: DbSession, actor: User = RequireManager) -> IdentityLink:
    """Link by hand. Always wins over an automatic email match."""
    scope = OrgScope(db, actor.org_id)
    oncall_connection = await scope.get(OncallConnection, payload.oncall_connection_id)
    chat_connection = await scope.get(ChatConnection, payload.chat_connection_id)
    if oncall_connection is None or chat_connection is None:
        raise NotFound("Connection not found")

    credentials = await oncall_connections.credentials_for(db, oncall_connection)
    people = {
        person.external_id: person
        for person in await get_oncall_provider(oncall_connection.kind).list_users(credentials)
    }
    person = people.get(payload.provider_user_id)
    if person is None:
        raise BadRequest("That person is not in the on-call provider's directory")

    chat_credentials = await chat_connections.credentials_for(db, chat_connection)
    provider = get_chat_provider(chat_connection.kind)
    # Confirm the chat account exists rather than storing an id that will fail
    # silently at the next handoff.
    chat_user = None
    if person.email:
        chat_user = await provider.find_user_by_email(chat_credentials, person.email)
    chat_user_name = (
        chat_user.name if chat_user and chat_user.external_id == payload.chat_user_id else None
    )

    link = await identity_resolver.set_manual_link(
        db,
        org_id=actor.org_id,
        oncall_connection_id=payload.oncall_connection_id,
        chat_connection_id=payload.chat_connection_id,
        provider_user_id=payload.provider_user_id,
        provider_email=person.email,
        provider_name=person.name,
        chat_user_id=payload.chat_user_id,
        chat_user_name=chat_user_name,
    )
    await db.commit()
    return link


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(link_id: uuid.UUID, db: DbSession, actor: User = RequireManager) -> None:
    link = await OrgScope(db, actor.org_id).get(IdentityLink, link_id)
    if link is None:
        raise NotFound("Link not found")
    await db.delete(link)
    await db.commit()
