"""Signup, login, logout, session introspection and invite acceptance."""

import uuid

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.v1.schemas import OrganizationOut, Password, SessionOut, UserOut
from app.core import ratelimit
from app.core.cookies import clear_auth_cookies, set_auth_cookies
from app.core.deps import CurrentUser, DbSession, RedisClient
from app.core.errors import Unauthorized
from app.core.sessions import SESSION_COOKIE, create_session, delete_session
from app.db.models import Organization
from app.services import accounts

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_ATTEMPT_LIMIT = 10
LOGIN_WINDOW_SECONDS = 900


class SignupIn(BaseModel):
    organization_name: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: Password


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    name: str = Field(min_length=1, max_length=120)
    password: Password


async def _start_session(
    response: Response, redis: RedisClient, user_id: uuid.UUID, org_id: uuid.UUID
) -> str:
    session_token, csrf_token = await create_session(redis, user_id, org_id)
    set_auth_cookies(response, session_token, csrf_token)
    return csrf_token


@router.post("/signup", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupIn, response: Response, db: DbSession, redis: RedisClient
) -> SessionOut:
    org, owner = await accounts.create_organization_with_owner(
        db,
        org_name=payload.organization_name,
        name=payload.name,
        email=payload.email,
        password=payload.password,
    )
    await db.commit()

    csrf_token = await _start_session(response, redis, owner.id, org.id)
    return SessionOut(
        user=UserOut.model_validate(owner),
        organization=OrganizationOut.model_validate(org),
        csrf_token=csrf_token,
    )


@router.post("/login", response_model=SessionOut)
async def login(
    payload: LoginIn, request: Request, response: Response, db: DbSession, redis: RedisClient
) -> SessionOut:
    # Throttle by address and client so neither a single account nor a single
    # source can be walked through a password list.
    client = request.client.host if request.client else "unknown"
    for key in (f"login:email:{payload.email.lower()}", f"login:ip:{client}"):
        result = await ratelimit.hit(
            redis, key, limit=LOGIN_ATTEMPT_LIMIT, window_seconds=LOGIN_WINDOW_SECONDS
        )
        if not result.allowed:
            raise Unauthorized("Too many attempts. Try again later.")

    user = await accounts.authenticate(db, email=payload.email, password=payload.password)
    if user is None:
        raise Unauthorized("Incorrect email or password")

    await ratelimit.reset(redis, f"login:email:{payload.email.lower()}")

    org = await db.scalar(select(Organization).where(Organization.id == user.org_id))
    assert org is not None

    csrf_token = await _start_session(response, redis, user.id, user.org_id)
    return SessionOut(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
        csrf_token=csrf_token,
    )


@router.post("/invites/accept", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def accept_invite(
    payload: AcceptInviteIn, response: Response, db: DbSession, redis: RedisClient
) -> SessionOut:
    user = await accounts.accept_invite(
        db, token=payload.token, name=payload.name, password=payload.password
    )
    org = await db.scalar(select(Organization).where(Organization.id == user.org_id))
    assert org is not None
    await db.commit()

    csrf_token = await _start_session(response, redis, user.id, user.org_id)
    return SessionOut(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
        csrf_token=csrf_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, redis: RedisClient) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await delete_session(redis, token)
    clear_auth_cookies(response)


@router.get("/me", response_model=SessionOut)
async def me(request: Request, user: CurrentUser, db: DbSession) -> SessionOut:
    org = await db.scalar(select(Organization).where(Organization.id == user.org_id))
    assert org is not None
    return SessionOut(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
        csrf_token=request.state.csrf_token,
    )
