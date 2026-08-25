"""Shared response shapes for the v1 API."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.security import MIN_PASSWORD_LENGTH
from app.db.models import UserRole

#: Applied to every password field so the policy lives in exactly one place.
Password = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)]


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class SessionOut(BaseModel):
    """What the SPA needs to render an authenticated shell."""

    user: UserOut
    organization: OrganizationOut
    csrf_token: str


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InviteCreatedOut(BaseModel):
    invite: InviteOut
    #: Shown once. There is no email delivery in the MVP, so the inviter shares this.
    accept_url: str


class OncallProviderOut(BaseModel):
    """Registry metadata. The UI renders connect options from this, not a hardcoded list."""

    kind: str
    display_name: str
    auth_modes: list[str]
    supports_oauth: bool
    oauth_configured: bool


class OncallConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    auth_mode: str
    display_name: str
    status: str
    scopes: str | None
    last_verified_at: datetime | None
    last_error: str | None
    schedules_synced_at: datetime | None
    created_at: datetime


class OncallScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    external_id: str
    name: str
    timezone: str
    description: str | None
    html_url: str | None
    synced_at: datetime


class ConnectionHealthOut(BaseModel):
    ok: bool
    detail: str


class ChatProviderOut(BaseModel):
    kind: str
    display_name: str
    install_configured: bool


class ChatConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    external_team_id: str
    team_name: str
    status: str
    scopes: str | None
    #: False when the workspace restricts user-group management and no installer
    #: token is held — the write path would have nothing to fall back to.
    has_user_token: bool
    last_verified_at: datetime | None
    last_error: str | None
    groups_synced_at: datetime | None
    created_at: datetime


class ChatGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    handle: str
    name: str
    is_active: bool
    synced_at: datetime


class ChatChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    name: str
    is_private: bool
    bot_is_member: bool
    synced_at: datetime


class SyncRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    enabled: bool
    oncall_connection_id: uuid.UUID
    schedule_external_id: str
    escalation_levels: list[int]
    chat_connection_id: uuid.UUID
    group_external_id: str
    fallback_chat_user_id: str | None
    notify_channel_external_id: str | None
    notify_on_change: bool
    message_template: str | None
    status: str
    last_synced_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    created_at: datetime


class ProviderUserOut(BaseModel):
    external_id: str
    name: str
    email: str | None = None


class ResolvedMemberOut(BaseModel):
    provider_user: ProviderUserOut
    chat_user_id: str
    chat_user_name: str | None
    source: str


class RulePreviewOut(BaseModel):
    """A dry run. Nothing is written to the chat workspace."""

    evaluated_at: datetime
    schedule_name: str
    on_call: list[ProviderUserOut]
    resolved: list[ResolvedMemberOut]
    unmapped: list[ProviderUserOut]
    desired_member_ids: list[str]
    current_member_ids: list[str]
    #: False when the rule is degraded: the handle is deliberately left alone, so
    #: the diff below is empty even if the membership differs.
    would_write: bool
    #: What would change if this ran for real.
    would_add: list[str]
    would_remove: list[str]
    used_fallback: bool
    shift_start: datetime | None
    next_change_at: datetime | None
    problems: list[str]


class IdentityLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_user_id: str
    provider_email: str | None
    provider_name: str | None
    chat_user_id: str
    chat_user_name: str | None
    source: str
    updated_at: datetime


class DirectoryEntryOut(BaseModel):
    """A provider person alongside their link, if any."""

    provider_user: ProviderUserOut
    link: IdentityLinkOut | None


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    previous_members: list[str] | None
    new_members: list[str] | None
    actions: list[str] | None
    problems: list[str] | None
    error: str | None


class MessagePreviewOut(BaseModel):
    """A rendered template. Nothing is posted."""

    text: str
    blocks: list[dict[str, Any]]
    problems: list[str]
    #: The values the sample render used, so the editor can label each variable.
    variables: dict[str, str]


class ActivityRunOut(SyncRunOut):
    """A run with enough context to read it without opening the rule."""

    rule_name: str


class OverviewOut(BaseModel):
    rules_total: int
    rules_by_status: dict[str, int]
    rules_paused: int
    connections_needing_attention: int
    #: The most recent run that actually changed who is on call.
    last_handoff_at: datetime | None
    last_run_at: datetime | None
