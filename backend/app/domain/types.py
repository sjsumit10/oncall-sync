"""Provider-agnostic value types.

Everything a vendor returns is normalized into these before it reaches business
logic, so adding Opsgenie or Grafana OnCall later is a new adapter rather than a
change to the sync engine.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class AuthMode(StrEnum):
    OAUTH = "oauth"
    API_KEY = "api_key"


@dataclass(frozen=True, slots=True)
class ProviderUser:
    """A person as the on-call provider knows them."""

    external_id: str
    name: str
    email: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleRef:
    external_id: str
    name: str
    timezone: str
    description: str | None = None
    html_url: str | None = None


@dataclass(frozen=True, slots=True)
class OncallSpan:
    """One person's shift on one schedule.

    The key normalization in the system: who is on call, from when to when, at
    which escalation level. The sync engine derives both the current on-call set
    and the exact time of the next handoff from a list of these, which is why one
    window fetch is enough per reconcile. ``end`` is None for an open-ended shift.
    """

    user: ProviderUser
    start: datetime
    end: datetime | None
    level: int = 1

    def covers(self, at: datetime) -> bool:
        return self.start <= at and (self.end is None or at < self.end)


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    ok: bool
    detail: str
    account_label: str | None = None


@dataclass(frozen=True, slots=True)
class Credentials:
    """Decrypted, ready-to-use credential material for one connection.

    The service layer refreshes expiring OAuth tokens before handing these over,
    so providers never deal with token lifecycle.
    """

    org_id: uuid.UUID
    auth_mode: AuthMode
    token: str


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str | None = None


@dataclass(frozen=True, slots=True)
class ChatCredentials:
    """Decrypted chat workspace tokens.

    Two tokens, because which one may write a user group depends on the
    workspace's User Groups permission setting rather than on our app: a bot
    token works when management is open to everyone, and a user token from an
    authorized installer is required when it is restricted to admins. Both are
    captured at install so the write path can fall back instead of failing.

    ``resource_id`` is for providers whose API is scoped one level below the
    connection itself — Graph's tag/channel/message endpoints all hang off a
    specific Team, not the whole tenant a Teams connection represents, unlike
    Slack where the connection *is* the workspace. Slack leaves it None.
    """

    org_id: uuid.UUID
    bot_token: str
    user_token: str | None = None
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChatUser:
    external_id: str
    name: str
    email: str | None = None
    is_bot: bool = False


@dataclass(frozen=True, slots=True)
class GroupRef:
    """A mentionable group: a Slack user group, or a Microsoft Teams tag later."""

    external_id: str
    handle: str
    name: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class ChannelRef:
    external_id: str
    name: str
    is_private: bool = False
    is_member: bool = False


@dataclass(frozen=True, slots=True)
class ChatInstall:
    external_team_id: str
    team_name: str
    bot_token: str
    bot_user_id: str | None = None
    user_token: str | None = None
    installing_user_external_id: str | None = None
    scopes: str | None = None
    user_scopes: str | None = None
    #: Only set by providers whose token expires (Teams). Slack leaves both None.
    refresh_token: str | None = None
    token_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MessageRef:
    channel_id: str
    ts: str


@dataclass(frozen=True, slots=True)
class Announcement:
    """A message to post, described in provider-neutral terms.

    The rendered body comes from the user's template; how it is presented — Slack
    Block Kit, a Teams adaptive card — is the adapter's business, so no vendor
    markup reaches the sync engine.
    """

    text: str
    kind: Literal["handoff", "problem"] = "handoff"
    schedule_name: str | None = None
    handle: str | None = None
    shift_end: datetime | None = None
