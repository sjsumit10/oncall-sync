"""One execution of the reconcile loop."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.models.oncall_connection import _enum

#: Without this, SQLAlchemy stores Python None as JSON 'null' rather than SQL
#: NULL, and every `IS NULL` check against these columns quietly matches.
NullableJSONB = JSONB(none_as_null=True)


class RunTrigger(StrEnum):
    #: The rule's next_run_at came due — either a predicted handoff or the
    #: periodic safety reconcile.
    SCHEDULED = "scheduled"
    #: Someone pressed "Sync now".
    MANUAL = "manual"
    #: A provider told us something changed, e.g. Slack's subteam_updated.
    EVENT = "event"


class RunStatus(StrEnum):
    SUCCESS = "success"
    #: Ran, but could not do what the rule asks — usually nobody resolved.
    DEGRADED = "degraded"
    FAILED = "failed"
    #: The rule is paused, or its connection needs reauthorising.
    SKIPPED = "skipped"


class SyncRun(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "sync_runs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sync_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger: Mapped[RunTrigger] = mapped_column(_enum(RunTrigger, "run_trigger"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus, "run_status"), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    previous_members: Mapped[list[str] | None] = mapped_column(NullableJSONB, nullable=True)
    new_members: Mapped[list[str] | None] = mapped_column(NullableJSONB, nullable=True)
    #: Human-readable record of what the run actually did.
    actions: Mapped[list[Any] | None] = mapped_column(NullableJSONB, nullable=True)
    #: Why the rule could not do what it was asked, if anything.
    problems: Mapped[list[Any] | None] = mapped_column(NullableJSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
