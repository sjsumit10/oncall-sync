"""Signup, login, logout, session introspection, invite acceptance and
password reset."""

import uuid

import structlog
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.v1.schemas import OrganizationOut, Password, SessionOut, UserOut
from app.config import get_settings
from app.core import ratelimit
from app.core.cookies import clear_auth_cookies, set_auth_cookies
from app.core.deps import CurrentUser, DbSession, RedisClient
from app.core.errors import BadRequest, TooManyRequests, Unauthorized
from app.core.security import hash_password
from app.core.sessions import SESSION_COOKIE, create_session, delete_session, delete_user_sessions
from app.db.models import Organization, User
from app.services import accounts, password_reset
from app.services.email import EmailNotConfigured, send_email

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_ATTEMPT_LIMIT = 10
LOGIN_WINDOW_SECONDS = 900

#: Stricter than login: a real user signs up once, so repeated attempts from
#: one source are either a mistake worth a short wait or a scripted mass
#: account/org creation attempt, not someone retrying a mistyped password.
SIGNUP_ATTEMPT_LIMIT = 5
SIGNUP_WINDOW_SECONDS = 900

#: Requesting a reset sends an email, so this is also an anti-mail-bombing
#: limit, not just an abuse-prevention one. Tighter window than login/signup
#: since a reset link is only valid for 5 minutes anyway — a real user has no
#: reason to ask for one 5 times in 2 minutes.
PASSWORD_RESET_REQUEST_LIMIT = 5
PASSWORD_RESET_WINDOW_SECONDS = 120

#: Guards token brute-forcing. Per IP always; per email too once a token
#: resolves to one, so repeated confirm attempts against the same account
#: are capped even across different (stolen or guessed) tokens.
PASSWORD_RESET_CONFIRM_LIMIT = 5
PASSWORD_RESET_CONFIRM_WINDOW_SECONDS = 120


async def _throttle(redis: RedisClient, *keys: str, limit: int, window_seconds: int) -> None:
    for key in keys:
        result = await ratelimit.hit(redis, key, limit=limit, window_seconds=window_seconds)
        if not result.allowed:
            raise TooManyRequests()


class SignupIn(BaseModel):
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


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    password: Password


async def _start_session(
    response: Response, redis: RedisClient, user_id: uuid.UUID, org_id: uuid.UUID
) -> str:
    session_token, csrf_token = await create_session(redis, user_id, org_id)
    set_auth_cookies(response, session_token, csrf_token)
    return csrf_token


@router.post("/signup", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupIn, request: Request, response: Response, db: DbSession, redis: RedisClient
) -> SessionOut:
    client = request.client.host if request.client else "unknown"
    await _throttle(
        redis,
        f"signup:email:{payload.email.lower()}",
        f"signup:ip:{client}",
        limit=SIGNUP_ATTEMPT_LIMIT,
        window_seconds=SIGNUP_WINDOW_SECONDS,
    )

    org, owner = await accounts.create_organization_with_owner(
        db,
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
        plans_enabled=get_settings().plans_enabled,
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
        plans_enabled=get_settings().plans_enabled,
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
        plans_enabled=get_settings().plans_enabled,
    )


@router.post("/password-reset/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    payload: PasswordResetRequestIn, request: Request, db: DbSession, redis: RedisClient
) -> None:
    """Always answers the same way, whether or not the email is registered.

    A response that differed here would let an attacker enumerate accounts by
    address — the entire reason to check "does this email exist" is exactly
    what this endpoint must never reveal.
    """
    client = request.client.host if request.client else "unknown"
    await _throttle(
        redis,
        f"password-reset:email:{payload.email.lower()}",
        f"password-reset:ip:{client}",
        limit=PASSWORD_RESET_REQUEST_LIMIT,
        window_seconds=PASSWORD_RESET_WINDOW_SECONDS,
    )

    email = accounts.normalize_email(payload.email)
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None and user.is_active:
        token = await password_reset.issue(redis, user_id=user.id)
        link = f"{get_settings().web_base_url}/reset-password?token={token}"
        try:
            await send_email(
                to=user.email,
                subject="Reset your On-Call Sync password",
                body=(
                    "Someone requested a password reset for this account.\n\n"
                    f"Reset it within 5 minutes: {link}\n\n"
                    "If you didn't request this, you can safely ignore this email — "
                    "your password will not change."
                ),
            )
        except EmailNotConfigured:
            log.error("password_reset.email_not_configured", user_id=str(user.id))
        except Exception:
            # Logged, not raised: the response must look identical to the
            # "no such account" case regardless of an SMTP-side failure.
            log.exception("password_reset.email_failed", user_id=str(user.id))
    return None


@router.post("/password-reset/confirm", response_model=SessionOut)
async def confirm_password_reset(
    payload: PasswordResetConfirmIn,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisClient,
) -> SessionOut:
    client = request.client.host if request.client else "unknown"
    await _throttle(
        redis,
        f"password-reset-confirm:ip:{client}",
        limit=PASSWORD_RESET_CONFIRM_LIMIT,
        window_seconds=PASSWORD_RESET_CONFIRM_WINDOW_SECONDS,
    )

    reset = await password_reset.consume(redis, payload.token)
    if reset is None:
        raise BadRequest("This link has expired or already been used. Request a new one.")

    user = await db.get(User, uuid.UUID(reset.user_id))
    if user is None or not user.is_active:
        raise BadRequest("This link has expired or already been used. Request a new one.")

    # Only knowable once the token resolves to an account — caps repeated
    # confirm attempts against the same user across different tokens, on top
    # of the IP limit above.
    await _throttle(
        redis,
        f"password-reset-confirm:email:{user.email.lower()}",
        limit=PASSWORD_RESET_CONFIRM_LIMIT,
        window_seconds=PASSWORD_RESET_CONFIRM_WINDOW_SECONDS,
    )

    user.password_hash = hash_password(payload.password)
    await db.commit()

    # A session open on a stolen or shared device must not survive a reset —
    # this is the one moment a compromised account can be reliably locked back
    # down, so every existing session goes, including the one that started
    # this request from another tab.
    await delete_user_sessions(redis, user.id)

    org = await db.scalar(select(Organization).where(Organization.id == user.org_id))
    assert org is not None

    csrf_token = await _start_session(response, redis, user.id, user.org_id)
    return SessionOut(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
        csrf_token=csrf_token,
        plans_enabled=get_settings().plans_enabled,
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
        plans_enabled=get_settings().plans_enabled,
    )
