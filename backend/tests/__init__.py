"""Test package.

Environment defaults live here because pytest imports the package before
conftest, and application settings are cached the moment a module imports them.
"""

import os
import pathlib


def _dotenv_port(key: str, default: str) -> str:
    """Read a published host port from the repo-root .env.

    The suite talks to the same containers development does, so it has to follow
    the same port remapping. Hardcoding one machine's ports here made a fresh
    clone fail with a connection refused that pointed nowhere useful.
    """
    env_file = pathlib.Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == key and value.strip():
                return value.strip()
    return default


_PG = _dotenv_port("POSTGRES_PORT", "5432")
_REDIS = _dotenv_port("REDIS_PORT", "6379")

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("COOKIE_SECURE", "false")
# A separate database from the development one: the suite truncates every table
# between tests.
os.environ.setdefault(
    "DATABASE_URL", f"postgresql+asyncpg://oncall_app:oncall_app@localhost:{_PG}/oncall_test"
)
os.environ.setdefault(
    "DATABASE_ADMIN_URL", f"postgresql+asyncpg://oncall:oncall@localhost:{_PG}/oncall_test"
)
os.environ.setdefault("REDIS_URL", f"redis://localhost:{_REDIS}/15")
# Must decode to exactly 32 bytes.
os.environ.setdefault("CREDENTIAL_KEK", "b25jYWxsLXN5bmMtdGVzdC1rZWstMzItYnl0ZXMhISE=")
