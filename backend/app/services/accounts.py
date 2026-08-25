"""Organization bootstrap, authentication and membership rules."""

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, Conflict, Forbidden
from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.db.models import Invite, Organization, User, UserRole
from app.db.session import bind_org

INVITE_TTL = timedelta(days=7)
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_STRIP.sub("-", name.lower()).strip("-")
    return slug[:50] or "org"


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name)
    slug = base
    while await db.scalar(select(Organization.id).where(Organization.slug == slug)):
        slug = f"{base}-{secrets.token_hex(3)}"
    return slug


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def email_exists(db: AsyncSession, email: str) -> bool:
    return (
        await db.scalar(select(User.id).where(User.email == normalize_email(email)))
    ) is not None


async def create_organization_with_owner(
    db: AsyncSession, *, name: str, email: str, password: str
) -> tuple[Organization, User]:
    email = normalize_email(email)
    if await email_exists(db, email):
        raise Conflict("An account with that email already exists")

    # No org name is collected at signup — the org starts named after its
    # owner's email and can be renamed later from Settings.
    org_name = email[:120]
    org = Organization(name=org_name, slug=await _unique_slug(db, org_name))
    db.add(org)
    await db.flush()

    owner = User(
        org_id=org.id,
        email=email,
        name=name.strip(),
        password_hash=hash_password(password),
        role=UserRole.OWNER,
    )
    db.add(owner)
    await db.flush()
    return org, owner


async def rename_organization(db: AsyncSession, *, org: Organization, name: str) -> Organization:
    org.name = name.strip()
    await db.flush()
    return org


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User | None:
    user = await db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        # Spend the same work on a miss as on a hit so response time does not
        # disclose whether the address is registered.
        verify_password(password, hash_password("timing-equalizer"))
        return None
    if not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


async def create_invite(
    db: AsyncSession, *, org_id: uuid.UUID, email: str, role: UserRole, invited_by: uuid.UUID
) -> tuple[Invite, str]:
    """Return the invite and its plaintext token — the only time the token exists."""
    email = normalize_email(email)
    if role is UserRole.OWNER:
        raise BadRequest("Ownership is transferred, not invited")
    if await email_exists(db, email):
        raise Conflict("That email already belongs to an account")

    existing = await db.scalar(
        select(Invite).where(
            Invite.org_id == org_id, Invite.email == email, Invite.accepted_at.is_(None)
        )
    )
    if existing is not None:
        raise Conflict("An invite is already pending for that email")

    token = generate_token()
    invite = Invite(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by_user_id=invited_by,
        expires_at=datetime.now(UTC) + INVITE_TTL,
    )
    db.add(invite)
    await db.flush()
    return invite, token


async def accept_invite(db: AsyncSession, *, token: str, name: str, password: str) -> User:
    invite = await db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None or invite.accepted_at is not None:
        raise BadRequest("This invite is no longer valid")
    if invite.expires_at <= datetime.now(UTC):
        raise BadRequest("This invite has expired")

    # The lookup above ran with no tenant context, through the narrow
    # invite_token_lookup policy. Now that the org is known, bind it so the
    # writes below are subject to org_isolation like any other request.
    await bind_org(db, invite.org_id)

    if await email_exists(db, invite.email):
        raise Conflict("That email already belongs to an account")

    user = User(
        org_id=invite.org_id,
        email=invite.email,
        name=name.strip(),
        password_hash=hash_password(password),
        role=invite.role,
    )
    db.add(user)
    invite.accepted_at = datetime.now(UTC)
    await db.flush()
    return user


async def count_owners(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(User.id)).where(
                User.org_id == org_id, User.role == UserRole.OWNER, User.is_active.is_(True)
            )
        )
    ) or 0


async def assert_not_last_owner(db: AsyncSession, user: User) -> None:
    """Guard against an org locking itself out of its own connections and rules."""
    if user.role is UserRole.OWNER and await count_owners(db, user.org_id) <= 1:
        raise Forbidden("An organization must keep at least one owner")
