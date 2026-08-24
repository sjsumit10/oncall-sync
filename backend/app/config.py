"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    app_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:5173"

    # The runtime connects as a least-privileged, non-superuser role. This is not
    # hygiene for its own sake: superusers bypass row-level security outright, and
    # FORCE ROW LEVEL SECURITY only covers the table owner, so connecting as either
    # would make the tenant-isolation policies decorative.
    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://oncall_app:oncall_app@localhost:5432/oncall"
    )
    # Owner role: runs migrations and the role bootstrap. Falls back to
    # database_url when unset, which is only ever right for throwaway setups.
    database_admin_url: PostgresDsn | None = None
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # Wraps the per-org data encryption keys. 32 bytes, urlsafe-base64 encoded.
    credential_kek: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("dev-only-change-me")
    # Secure by default; local development and the test suite turn it off so
    # cookies survive plain http.
    cookie_secure: bool = True

    # How often a rule is reconciled even when no handoff is expected. This is the
    # safety net for retroactive overrides, schedule edits and manual Slack drift.
    reconcile_interval_seconds: int = 300
    # How far ahead we look for the next shift boundary.
    oncall_window_days: int = 14
    # Beat tick: how often the worker claims rules whose next_run_at has passed.
    beat_interval_seconds: int = 30

    pagerduty_client_id: str = ""
    pagerduty_client_secret: SecretStr = SecretStr("")

    slack_client_id: str = ""
    slack_client_secret: SecretStr = SecretStr("")
    slack_signing_secret: SecretStr = SecretStr("")

    sentry_dsn: str = ""

    @property
    def admin_database_url(self) -> PostgresDsn:
        return self.database_admin_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
