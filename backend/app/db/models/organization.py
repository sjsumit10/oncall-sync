"""The tenant root. Everything else hangs off an organization."""

from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.models.oncall_connection import _enum


class OrgPlan(StrEnum):
    FREE = "free"
    STARTER = "starter"
    PREMIUM = "premium"


#: How many sync rules an organization on each plan may have at once.
PLAN_RULE_LIMITS: dict[OrgPlan, int] = {
    OrgPlan.FREE: 5,
    OrgPlan.STARTER: 100,
    OrgPlan.PREMIUM: 500,
}


class Organization(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    plan: Mapped[OrgPlan] = mapped_column(
        _enum(OrgPlan, "org_plan"), nullable=False, default=OrgPlan.FREE
    )
