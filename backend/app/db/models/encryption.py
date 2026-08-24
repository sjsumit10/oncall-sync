"""Per-organization data keys, wrapped by the environment's KEK."""

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class OrgDataKey(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "org_data_keys"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
