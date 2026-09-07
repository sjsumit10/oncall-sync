"""Organization settings: members and invites."""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    InviteCreatedOut,
    InviteOut,
    OrganizationOut,
    PlanInfoOut,
    PlanTierOut,
    UserOut,
)
from app.config import get_settings
from app.core.deps import CurrentUser, DbSession, RedisClient, require_role
from app.core.errors import BadRequest, Forbidden, NotFound
from app.core.sessions import delete_user_sessions
from app.db.models import (
    MANAGER_ROLES,
    PLAN_RULE_LIMITS,
    Invite,
    Organization,
    OrgPlan,
    SyncRule,
    User,
    UserRole,
)
from app.db.repository import OrgScope
from app.services import accounts

router = APIRouter(prefix="/org", tags=["organization"])

RequireManager = Depends(require_role(*MANAGER_ROLES))
RequireOwner = Depends(require_role(UserRole.OWNER))


class InviteIn(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.MEMBER


class RoleUpdateIn(BaseModel):
    role: UserRole


class OrganizationUpdateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class PlanUpdateIn(BaseModel):
    plan: OrgPlan


@router.get("", response_model=OrganizationOut)
async def get_organization(user: CurrentUser, db: DbSession) -> Organization:
    org = await db.get(Organization, user.org_id)
    if org is None:
        raise NotFound("Organization not found")
    return org


@router.patch("", response_model=OrganizationOut)
async def update_organization(
    payload: OrganizationUpdateIn, db: DbSession, actor: User = RequireOwner
) -> Organization:
    org = await db.get(Organization, actor.org_id)
    if org is None:
        raise NotFound("Organization not found")
    org = await accounts.rename_organization(db, org=org, name=payload.name)
    await db.commit()
    return org


async def _rule_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    count = await db.scalar(select(func.count(SyncRule.id)).where(SyncRule.org_id == org_id))
    return count or 0


def _plan_info(org: Organization, rule_count: int) -> PlanInfoOut:
    tiers = [PlanTierOut(plan=plan, rule_limit=limit) for plan, limit in PLAN_RULE_LIMITS.items()]
    return PlanInfoOut(
        plan=org.plan,
        rule_limit=PLAN_RULE_LIMITS[org.plan],
        rule_count=rule_count,
        tiers=tiers,
    )


@router.get("/plan", response_model=PlanInfoOut)
async def get_plan(user: CurrentUser, db: DbSession) -> PlanInfoOut:
    org = await db.get(Organization, user.org_id)
    if org is None:
        raise NotFound("Organization not found")
    return _plan_info(org, await _rule_count(db, user.org_id))


@router.patch("/plan", response_model=PlanInfoOut)
async def update_plan(
    payload: PlanUpdateIn, db: DbSession, actor: User = RequireOwner
) -> PlanInfoOut:
    org = await db.get(Organization, actor.org_id)
    if org is None:
        raise NotFound("Organization not found")

    count = await _rule_count(db, actor.org_id)
    new_limit = PLAN_RULE_LIMITS[payload.plan]
    if count > new_limit:
        raise BadRequest(
            f"You have {count} sync rules, which is more than the {payload.plan.value} "
            f"plan's limit of {new_limit}. Remove some rules before downgrading."
        )

    org.plan = payload.plan
    await db.commit()
    return _plan_info(org, count)


@router.get("/members", response_model=list[UserOut])
async def list_members(user: CurrentUser, db: DbSession) -> list[User]:
    scope = OrgScope(db, user.org_id)
    return sorted(await scope.list(User), key=lambda u: u.created_at)


@router.patch("/members/{user_id}", response_model=UserOut)
async def update_member_role(
    user_id: uuid.UUID,
    payload: RoleUpdateIn,
    db: DbSession,
    actor: User = RequireOwner,
) -> User:
    scope = OrgScope(db, actor.org_id)
    member = await scope.get(User, user_id)
    if member is None:
        raise NotFound("Member not found")

    if member.role is payload.role:
        return member
    if member.role is UserRole.OWNER:
        await accounts.assert_not_last_owner(db, member)

    member.role = payload.role
    await db.commit()
    return member


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: uuid.UUID,
    db: DbSession,
    redis: RedisClient,
    actor: User = RequireManager,
) -> None:
    if user_id == actor.id:
        raise BadRequest("Use account deletion to remove yourself")

    scope = OrgScope(db, actor.org_id)
    member = await scope.get(User, user_id)
    if member is None:
        raise NotFound("Member not found")
    if member.role is UserRole.OWNER and actor.role is not UserRole.OWNER:
        raise Forbidden("Only an owner can remove another owner")

    await accounts.assert_not_last_owner(db, member)
    await db.delete(member)
    await db.commit()
    # Revoke immediately rather than letting their session ride out its TTL.
    await delete_user_sessions(redis, member.id)


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(db: DbSession, actor: User = RequireManager) -> list[Invite]:
    scope = OrgScope(db, actor.org_id)
    pending = await scope.list(Invite, Invite.accepted_at.is_(None))
    return sorted(pending, key=lambda i: i.created_at, reverse=True)


@router.post("/invites", response_model=InviteCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteIn, db: DbSession, actor: User = RequireManager
) -> InviteCreatedOut:
    if payload.role is UserRole.ADMIN and actor.role is not UserRole.OWNER:
        raise Forbidden("Only an owner can invite an admin")

    invite, token = await accounts.create_invite(
        db, org_id=actor.org_id, email=payload.email, role=payload.role, invited_by=actor.id
    )
    await db.commit()

    return InviteCreatedOut(
        invite=InviteOut.model_validate(invite),
        accept_url=f"{get_settings().web_base_url}/invite/{token}",
    )


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: uuid.UUID, db: DbSession, actor: User = RequireManager) -> None:
    scope = OrgScope(db, actor.org_id)
    invite = await scope.get(Invite, invite_id)
    if invite is None:
        raise NotFound("Invite not found")
    if invite.accepted_at is not None:
        raise BadRequest("That invite has already been accepted")

    await db.delete(invite)
    await db.commit()
