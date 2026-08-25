"""Two providers written from scratch against the interfaces.

The extensibility proof. Neither of these shares a single line with the Slack or
PagerDuty adapters, and the sync engine has never heard of them. If reconciling a
rule through this pair needs any change to app/services/, app/api/ or app/db/,
the abstraction has failed and adding Opsgenie or Teams later will hurt.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.errors import EmptyMembershipRejected
from app.domain.types import (
    Announcement,
    AuthMode,
    ChannelRef,
    ChatCredentials,
    ChatInstall,
    ChatUser,
    Credentials,
    GroupRef,
    MessageRef,
    OncallSpan,
    ProviderHealth,
    ProviderUser,
    ScheduleRef,
)

ONCALL_KIND = "fake-oncall"
CHAT_KIND = "fake-chat"


@dataclass
class FakeOncallProvider:
    """A rota held in memory. No HTTP, no vendor payloads."""

    kind: str = ONCALL_KIND
    display_name: str = "Fake On-Call"
    auth_modes: tuple[AuthMode, ...] = (AuthMode.API_KEY,)

    schedules: list[ScheduleRef] = field(
        default_factory=lambda: [ScheduleRef("SCHED-1", "Rota", "UTC")]
    )
    spans: list[OncallSpan] = field(default_factory=list)
    people: list[ProviderUser] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def verify(self, credentials: Credentials) -> ProviderHealth:
        self.calls.append("verify")
        return ProviderHealth(ok=True, detail="Fake provider is fine")

    async def list_schedules(self, credentials: Credentials) -> list[ScheduleRef]:
        self.calls.append("list_schedules")
        return list(self.schedules)

    async def get_oncall_window(
        self, credentials: Credentials, schedule_id: str, since: datetime, until: datetime
    ) -> list[OncallSpan]:
        self.calls.append("get_oncall_window")
        return [
            span
            for span in self.spans
            if span.start < until and (span.end is None or span.end > since)
        ]

    async def list_users(self, credentials: Credentials) -> list[ProviderUser]:
        self.calls.append("list_users")
        return list(self.people)


@dataclass
class FakeChatProvider:
    """A workspace held in memory, with its own mention syntax and rich format."""

    kind: str = CHAT_KIND
    display_name: str = "Fake Chat"

    groups: dict[str, list[str]] = field(default_factory=lambda: {"GRP-1": []})
    users_by_email: dict[str, ChatUser] = field(default_factory=dict)
    posted: list[Announcement] = field(default_factory=list)
    #: Set to simulate a workspace that refuses group writes.
    write_error: Exception | None = None

    def install_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://fake.chat/install?state={state}"

    async def complete_install(self, *, code: str, redirect_uri: str) -> ChatInstall:
        return ChatInstall(external_team_id="TEAM-1", team_name="Fake Team", bot_token="fake-token")

    async def verify(self, credentials: ChatCredentials) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="Fake chat is fine")

    async def list_groups(self, credentials: ChatCredentials) -> list[GroupRef]:
        return [GroupRef(gid, f"handle-{gid}", f"Group {gid}") for gid in self.groups]

    async def list_channels(self, credentials: ChatCredentials) -> list[ChannelRef]:
        return [ChannelRef("CHAN-1", "ops", is_member=True)]

    async def get_group_members(self, credentials: ChatCredentials, group_id: str) -> list[str]:
        return list(self.groups.get(group_id, []))

    async def set_group_members(
        self, credentials: ChatCredentials, group_id: str, member_ids: list[str]
    ) -> None:
        if not member_ids:
            raise EmptyMembershipRejected("Refusing to empty a group")
        if self.write_error is not None:
            raise self.write_error
        self.groups[group_id] = list(member_ids)

    async def find_user_by_email(self, credentials: ChatCredentials, email: str) -> ChatUser | None:
        return self.users_by_email.get(email)

    def format_mention(self, chat_user_id: str) -> str:
        # Deliberately unlike Slack's <@id>: if this shows up in a message, the
        # engine took its mention syntax from the provider as it should.
        return f"@@{chat_user_id}@@"

    def render_announcement(
        self, announcement: Announcement
    ) -> tuple[str, list[dict[str, object]]]:
        return announcement.text, [{"fake_card": announcement.text}]

    async def post_message(
        self,
        credentials: ChatCredentials,
        channel_id: str,
        text: str,
        blocks: list[dict[str, object]] | None = None,
    ) -> MessageRef:
        self.posted.append(Announcement(text=text))
        return MessageRef(channel_id=channel_id, ts="1")

    async def post_announcement(
        self, credentials: ChatCredentials, channel_id: str, announcement: Announcement
    ) -> MessageRef:
        self.posted.append(announcement)
        return MessageRef(channel_id=channel_id, ts="1")


def person(external_id: str, name: str, email: str) -> ProviderUser:
    return ProviderUser(external_id=external_id, name=name, email=email)


def chat_user(external_id: str, name: str, email: str) -> ChatUser:
    return ChatUser(external_id=external_id, name=name, email=email)


def new_id() -> uuid.UUID:
    return uuid.uuid4()
