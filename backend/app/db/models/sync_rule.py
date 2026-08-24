"""The core mapping: one on-call schedule to one chat group handle."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.models.oncall_connection import _enum


class RuleStatus(StrEnum):
    #: Created but never reconciled.
    PENDING = "pending"
    HEALTHY = "healthy"
    #: Reconciled, but the outcome was not what the rule asks for — usually
    #: nobody resolved to a chat account. The group is left untouched.
    DEGRADED = "degraded"
    #: Repeated provider failures.
    FAILING = "failing"


class SyncRule(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "sync_rules"
    __table_args__ = (
        # Two rules writing one group would fight each other on every handoff,
        # each undoing the other. One writer per handle.
        UniqueConstraint("chat_connection_id", "group_external_id", name="uq_one_rule_per_group"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- source: where on-call comes from -----------------------------------
    oncall_connection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("oncall_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schedule_external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Escalation levels to include; the union is taken across them. Defaults to
    #: level 1 only, which is "the person actually holding the pager".
    escalation_levels: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=sa.text("'{1}'::integer[]")
    )

    # --- target: the handle to keep pointed at them --------------------------
    chat_connection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Slack refuses to leave a user group empty, so a rule that resolves to
    #: nobody falls back to this person rather than clearing the handle.
    fallback_chat_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- announcement --------------------------------------------------------
    notify_channel_external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: False is "quiet mode": keep the handle correct, post nothing.
    notify_on_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Rendered in M6; null means the built-in default.
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- reconcile state -----------------------------------------------------
    #: Last synced membership, used to tell a real handoff from drift repair.
    current_members: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The scheduler clock. M5's beat claims rules whose time has come.
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RuleStatus] = mapped_column(
        _enum(RuleStatus, "rule_status"), nullable=False, default=RuleStatus.PENDING
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IdentitySource(StrEnum):
    #: Matched automatically on email address.
    AUTO_EMAIL = "auto_email"
    #: Set by a human. Always wins over an automatic match.
    MANUAL = "manual"


class IdentityLink(Base, UUIDPrimaryKey, Timestamps):
    """A PagerDuty person matched to their chat account.

    Email is the only join key the providers share, and it is also the most common
    real-world failure: aliases, contractors, SSO variance. The manual override is
    not a nice-to-have.
    """

    __tablename__ = "identity_links"
    __table_args__ = (
        UniqueConstraint(
            "oncall_connection_id",
            "provider_user_id",
            "chat_connection_id",
            name="uq_identity_per_pair",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    oncall_connection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("oncall_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    chat_connection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    chat_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source: Mapped[IdentitySource] = mapped_column(
        _enum(IdentitySource, "identity_source"), nullable=False, default=IdentitySource.AUTO_EMAIL
    )
