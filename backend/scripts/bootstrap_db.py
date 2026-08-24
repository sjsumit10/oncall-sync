"""Create the least-privileged application role and grant it access.

Run once per database, before migrations.

The application must not connect as a superuser or as the table owner: superusers
bypass row-level security entirely, and FORCE ROW LEVEL SECURITY only reaches the
owner. Connecting as either would leave the tenant-isolation policies in the
migrations doing nothing at all.

Credentials come from DATABASE_URL (the app role) and DATABASE_ADMIN_URL (the
owner), so there is no third place to keep them in sync.
"""

import asyncio
import re
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

_SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def bootstrap() -> None:
    settings = get_settings()
    app_url = settings.database_url
    admin_url = settings.admin_database_url

    # PostgresDsn is a multi-host URL, so credentials live on the host entries.
    app_host = app_url.hosts()[0]
    admin_host = admin_url.hosts()[0]
    role = app_host.get("username") or ""
    password = app_host.get("password") or ""
    owner = admin_host.get("username") or ""

    if not _SAFE_IDENTIFIER.match(role):
        raise SystemExit(f"Refusing to use {role!r} as a role name")
    if role == owner:
        raise SystemExit(
            f"DATABASE_URL and DATABASE_ADMIN_URL both use role {role!r}. The app "
            "must connect as a separate non-owner role or RLS will not apply."
        )

    engine = create_async_engine(str(admin_url), isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        # DDL cannot be parameterized. The role name is regex-validated above and
        # the password is quote-escaped, both from local configuration.
        await conn.execute(
            text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {_quote_literal(role)}) THEN
                    CREATE ROLE {role} LOGIN PASSWORD {_quote_literal(password)};
                ELSE
                    ALTER ROLE {role} LOGIN PASSWORD {_quote_literal(password)};
                END IF;
            END
            $$;
            """)
        )
        # Belt and braces: a role created elsewhere might carry either attribute.
        await conn.execute(text(f"ALTER ROLE {role} NOSUPERUSER NOBYPASSRLS"))

        database = admin_url.path.lstrip("/") if admin_url.path else ""
        await conn.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {role}'))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        # Covers tables that already exist...
        await conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
        )
        await conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))
        # ...and everything future migrations create, without a follow-up grant.
        await conn.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
            )
        )
        await conn.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
                f"GRANT USAGE, SELECT ON SEQUENCES TO {role}"
            )
        )
    await engine.dispose()
    print(f"Bootstrapped role {role!r} in database {database!r}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(bootstrap())
