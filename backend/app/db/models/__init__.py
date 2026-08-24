"""Model registry.

Every model must be imported here so Alembic autogenerate and Base.metadata see it.
"""

from app.db.models.chat_connection import ChatChannel, ChatConnection, ChatGroup
from app.db.models.encryption import OrgDataKey
from app.db.models.invite import Invite
from app.db.models.oncall_connection import ConnectionStatus, OncallConnection, OncallSchedule
from app.db.models.organization import Organization
from app.db.models.sync_rule import IdentityLink, IdentitySource, RuleStatus, SyncRule
from app.db.models.user import MANAGER_ROLES, User, UserRole

__all__ = [
    "MANAGER_ROLES",
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
    "Organization",
    "RuleStatus",
    "SyncRule",
    "User",
    "UserRole",
]
