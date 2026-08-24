"""Test package.

Environment defaults live here because pytest imports the package before
conftest, and application settings are cached the moment a module imports them.
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://oncall_app:oncall_app@localhost:55432/oncall_test"
)
os.environ.setdefault(
    "DATABASE_ADMIN_URL", "postgresql+asyncpg://oncall:oncall@localhost:55432/oncall_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/15")
# Must decode to exactly 32 bytes.
os.environ.setdefault("CREDENTIAL_KEK", "b25jYWxsLXN5bmMtdGVzdC1rZWstMzItYnl0ZXMhISE=")
