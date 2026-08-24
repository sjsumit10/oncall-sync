"""An installed chat workspace and its cached groups and channels."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.models.oncall_connection import ConnectionStatus, _enum


class ChatConnection(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "chat_connections"
    __table_args__ = (
        UniqueConstraint("org_id", "kind", "external_team_id", name="uq_workspace_per_org"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    external_team_id: Mapped[str] = mapped_column(String(120), nullable=False)
    team_name: Mapped[str] = mapped_column(String(255), nullable=False)

    bot_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    bot_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Present when the installer granted user scopes. Required only by workspaces
    #: that restrict User Groups management to admins.
    user_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    installing_user_external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    installed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_scopes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ConnectionStatus] = mapped_column(
        _enum(ConnectionStatus, "connection_status"),
        nullable=False,
        default=ConnectionStatus.ACTIVE,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    groups_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChatGroup(Base, UUIDPrimaryKey, Timestamps):
    """Cached mentionable groups — Slack user groups, Teams tags later."""

    __tablename__ = "chat_groups"
    __table_args__ = (
        UniqueConstraint("chat_connection_id", "external_id", name="uq_group_per_workspace"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_connection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatChannel(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "chat_channels"
    __table_args__ = (
        UniqueConstraint("chat_connection_id", "external_id", name="uq_channel_per_workspace"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_connection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Slack only delivers messages to channels the bot has joined, so this is
    #: surfaced in the picker rather than discovered at the first failed post.
    bot_is_member: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
