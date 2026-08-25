"""Matching on-call provider people to their chat accounts.

Email is the only key PagerDuty and Slack share, so it is the automatic path —
and also the most common real-world failure, through aliases, contractors and SSO
variance. A human-set link therefore always wins over an automatic match and is
never overwritten by one.
"""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.db.models import (
    ChatConnection,
    IdentityLink,
    IdentitySource,
    OncallConnection,
)
from app.domain.registry import get_chat_provider
from app.domain.types import ProviderUser
from app.services import chat_connections

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedMember:
    provider_user: ProviderUser
    chat_user_id: str
    chat_user_name: str | None
    source: IdentitySource


@dataclass(frozen=True, slots=True)
class Resolution:
    resolved: list[ResolvedMember]
    unmapped: list[ProviderUser]

    @property
    def chat_user_ids(self) -> list[str]:
        # Deduplicated but order-stable: one person can hold two levels at once.
        seen: dict[str, None] = {}
        for member in self.resolved:
            seen.setdefault(member.chat_user_id, None)
        return list(seen)


async def existing_links(
    db: AsyncSession, *, oncall_connection_id: uuid.UUID, chat_connection_id: uuid.UUID
) -> dict[str, IdentityLink]:
    rows = await db.scalars(
        select(IdentityLink).where(
            IdentityLink.oncall_connection_id == oncall_connection_id,
            IdentityLink.chat_connection_id == chat_connection_id,
        )
    )
    return {row.provider_user_id: row for row in rows}


async def resolve(
    db: AsyncSession,
    *,
    oncall_connection: OncallConnection,
    chat_connection: ChatConnection,
    users: list[ProviderUser],
) -> Resolution:
    """Map provider users to chat user ids, learning new links as it goes."""
    links = await existing_links(
        db,
        oncall_connection_id=oncall_connection.id,
        chat_connection_id=chat_connection.id,
    )

    resolved: list[ResolvedMember] = []
    unmapped: list[ProviderUser] = []
    credentials = None

    for user in users:
        link = links.get(user.external_id)
        if link is not None:
            resolved.append(
                ResolvedMember(
                    provider_user=user,
                    chat_user_id=link.chat_user_id,
                    chat_user_name=link.chat_user_name,
                    source=link.source,
                )
            )
            continue

        if not user.email:
            unmapped.append(user)
            continue

        # Lazily built: a fully linked team costs no chat API calls at all.
        if credentials is None:
            credentials = await chat_connections.credentials_for(db, chat_connection)

        chat_user = await get_chat_provider(chat_connection.kind).find_user_by_email(
            credentials, user.email
        )
        if chat_user is None:
            unmapped.append(user)
            metrics.IDENTITIES_UNMAPPED.inc()
            log.info(
                "identity.unmapped", provider_user=user.external_id, email_domain=_domain(user)
            )
            continue

        db.add(
            IdentityLink(
                org_id=oncall_connection.org_id,
                oncall_connection_id=oncall_connection.id,
                provider_user_id=user.external_id,
                provider_email=user.email,
                provider_name=user.name,
                chat_connection_id=chat_connection.id,
                chat_user_id=chat_user.external_id,
                chat_user_name=chat_user.name,
                source=IdentitySource.AUTO_EMAIL,
            )
        )
        resolved.append(
            ResolvedMember(
                provider_user=user,
                chat_user_id=chat_user.external_id,
                chat_user_name=chat_user.name,
                source=IdentitySource.AUTO_EMAIL,
            )
        )

    return Resolution(resolved=resolved, unmapped=unmapped)


def _domain(user: ProviderUser) -> str | None:
    """Log the domain, never the address itself."""
    return user.email.rsplit("@", 1)[-1] if user.email and "@" in user.email else None


async def set_manual_link(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    oncall_connection_id: uuid.UUID,
    chat_connection_id: uuid.UUID,
    provider_user_id: str,
    provider_email: str | None,
    provider_name: str | None,
    chat_user_id: str,
    chat_user_name: str | None,
) -> IdentityLink:
    """Create or replace a link by hand. Overrides any automatic match."""
    link = await db.scalar(
        select(IdentityLink).where(
            IdentityLink.oncall_connection_id == oncall_connection_id,
            IdentityLink.chat_connection_id == chat_connection_id,
            IdentityLink.provider_user_id == provider_user_id,
        )
    )
    if link is None:
        link = IdentityLink(
            org_id=org_id,
            oncall_connection_id=oncall_connection_id,
            chat_connection_id=chat_connection_id,
            provider_user_id=provider_user_id,
        )
        db.add(link)

    link.provider_email = provider_email
    link.provider_name = provider_name
    link.chat_user_id = chat_user_id
    link.chat_user_name = chat_user_name
    link.source = IdentitySource.MANUAL
    await db.flush()
    return link
