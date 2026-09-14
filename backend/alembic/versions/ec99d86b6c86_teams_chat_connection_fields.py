"""teams chat connection fields

Revision ID: ec99d86b6c86
Revises: 6bc3c5f84710
Create Date: 2026-09-08 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ec99d86b6c86"
down_revision: str | None = "6bc3c5f84710"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_connections", sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "chat_connections",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chat_connections", sa.Column("external_resource_id", sa.String(length=120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_connections", "external_resource_id")
    op.drop_column("chat_connections", "token_expires_at")
    op.drop_column("chat_connections", "refresh_token_enc")
