"""Test fixtures."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.core.crypto import reset_key_cache
from app.core.redis import close_redis, get_redis
from app.core.sessions import CSRF_COOKIE, CSRF_HEADER
from app.db.models import Organization
from app.db.session import SessionLocal, set_current_org
from app.main import app
from scripts.bootstrap_db import bootstrap

TABLES = (
    "sync_runs",
    "sync_rules",
    "identity_links",
    "chat_channels",
    "chat_groups",
    "chat_connections",
    "oncall_schedules",
    "oncall_connections",
    "org_data_keys",
    "invites",
    "users",
    "organizations",
)


#: Owner connection. Used only for schema setup and truncation — never for the
#: queries under test, which must run as the least-privileged app role so RLS applies.
admin_engine = create_async_engine(str(get_settings().admin_database_url))


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    assert get_settings().environment == "test", "refusing to run tests outside ENVIRONMENT=test"
    asyncio.run(bootstrap())
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture(autouse=True)
def _default_license_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the default license mode regardless of the developer's local .env,
    so plan-quota tests don't silently change behavior based on it."""
    monkeypatch.setattr(get_settings(), "license_mode", "closed")


@pytest.fixture(autouse=True)
async def clean_state() -> AsyncIterator[None]:
    set_current_org(None)
    async with admin_engine.begin() as conn:
        # TRUNCATE is not subject to row-level security, so this clears every tenant.
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    await get_redis().flushdb()
    # Data keys are cached per process; truncating the table alone would
    # leave the previous test's keys live.
    reset_key_cache()
    yield
    set_current_org(None)


@pytest.fixture(scope="session", autouse=True)
async def _close_connections() -> AsyncIterator[None]:
    yield
    await close_redis()
    await admin_engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """A client with its own cookie jar — one jar per simulated browser."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as instance:
        yield instance


def csrf(client: AsyncClient) -> dict[str, str]:
    """Headers echoing the CSRF cookie, as the SPA does."""
    return {CSRF_HEADER: client.cookies.get(CSRF_COOKIE, "")}


async def signup(
    client: AsyncClient,
    *,
    email: str = "owner@acme.dev",
    password: str = "correct-horse-battery",
    name: str = "Ada",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/signup",
        json={"name": name, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def invitee() -> AsyncIterator[AsyncClient]:
    """A second browser, for the person receiving an invite."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as instance:
        yield instance


@pytest.fixture
async def org_id() -> uuid.UUID:
    """An organization created directly, for tests that need no HTTP session.

    Binds the tenant the way get_current_user does for a request, because RLS
    refuses writes to tenant tables when no org is bound.
    """
    async with SessionLocal() as session:
        org = Organization(name="Direct", slug=f"direct-{uuid.uuid4().hex[:8]}")
        session.add(org)
        await session.commit()
    set_current_org(org.id)
    return org.id


async def make_org(name: str) -> uuid.UUID:
    """A second organization, for cross-tenant assertions."""
    async with SessionLocal() as session:
        org = Organization(name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}")
        session.add(org)
        await session.commit()
        return org.id
