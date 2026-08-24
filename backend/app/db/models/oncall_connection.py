"""A connected on-call provider account (PagerDuty today)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.domain.types import AuthMode


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    #: Credentials rejected by the provider — the user must reconnect.
    NEEDS_REAUTH = "needs_reauth"
    #: Repeated non-auth failures; retried, but surfaced in the UI.
    ERROR = "error"


def _enum(python_enum: type[StrEnum], name: str) -> Enum:
    return Enum(python_enum, name=name, values_callable=lambda e: [m.value for m in e])


class OncallConnection(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "oncall_connections"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Registry key, e.g. "pagerduty". Not an enum: adding a provider must not
    #: require a schema migration.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    auth_mode: Mapped[AuthMode] = mapped_column(_enum(AuthMode, "auth_mode"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: Envelope-encrypted. Never logged, never returned by the API.
    credentials_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    #: Plaintext on purpose: refresh scheduling must not require decryption.
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ConnectionStatus] = mapped_column(
        _enum(ConnectionStatus, "connection_status"),
        nullable=False,
        default=ConnectionStatus.ACTIVE,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedules_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OncallSchedule(Base, UUIDPrimaryKey, Timestamps):
    """Cached schedule list.

    A convenience mirror for pickers and rule display only — never the source of
    truth for who is on call. That is always fetched live.
    """

    __tablename__ = "oncall_schedules"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_schedule_per_conn"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("oncall_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="UTC")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
