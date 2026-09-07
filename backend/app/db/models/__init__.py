"""Model registry.

Every model must be imported here so Alembic autogenerate and Base.metadata see it.
"""

from app.db.models.chat_connection import ChatChannel, ChatConnection, ChatGroup
from app.db.models.encryption import OrgDataKey
from app.db.models.invite import Invite
from app.db.models.oncall_connection import ConnectionStatus, OncallConnection, OncallSchedule
from app.db.models.organization import PLAN_RULE_LIMITS, Organization, OrgPlan
from app.db.models.sync_rule import IdentityLink, IdentitySource, RuleStatus, SyncRule
from app.db.models.sync_run import RunStatus, RunTrigger, SyncRun
from app.db.models.user import MANAGER_ROLES, User, UserRole

__all__ = [
    "MANAGER_ROLES",
    "PLAN_RULE_LIMITS",
    "ChatChannel",
    "ChatConnection",
    "ChatGroup",
    "ConnectionStatus",
    "IdentityLink",
    "IdentitySource",
    "Invite",
    "OncallConnection",
    "OncallSchedule",
    "OrgDataKey",
    "OrgPlan",
    "Organization",
    "RuleStatus",
    "RunStatus",
    "RunTrigger",
    "SyncRule",
    "SyncRun",
    "User",
    "UserRole",
]
