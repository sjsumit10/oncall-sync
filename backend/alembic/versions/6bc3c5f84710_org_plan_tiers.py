"""org plan tiers

Revision ID: 6bc3c5f84710
Revises: ea58a629effd
Create Date: 2026-09-06 07:22:54.812531+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6bc3c5f84710"
down_revision: str | None = "ea58a629effd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    org_plan = sa.Enum("free", "starter", "premium", name="org_plan")
    org_plan.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "organizations",
        sa.Column("plan", org_plan, nullable=False, server_default="free"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "plan")
    sa.Enum(name="org_plan").drop(op.get_bind(), checkfirst=True)
