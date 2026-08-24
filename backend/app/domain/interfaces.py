"""The contracts business logic is written against.

Nothing outside app/providers/ may import a vendor SDK or branch on a vendor
name. If a change to the sync engine is ever needed to add a provider, the
interface is wrong.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.types import (
    AuthMode,
    ChannelRef,
    ChatCredentials,
    ChatInstall,
    ChatUser,
    Credentials,
    GroupRef,
    MessageRef,
    OAuthTokens,
    OncallSpan,
    ProviderHealth,
    ProviderUser,
    ScheduleRef,
)


@runtime_checkable
class OncallProvider(Protocol):
    """A source of on-call schedules: PagerDuty today, Opsgenie tomorrow."""

    kind: str
    display_name: str
    auth_modes: tuple[AuthMode, ...]

    async def verify(self, credentials: Credentials) -> ProviderHealth:
        """Cheap round-trip proving the credentials work and naming the account."""
        ...

    async def list_schedules(self, credentials: Credentials) -> list[ScheduleRef]: ...

    async def get_oncall_window(
        self, credentials: Credentials, schedule_id: str, since: datetime, until: datetime
    ) -> list[OncallSpan]:
        """Every shift overlapping [since, until), including overrides."""
        ...

    async def list_users(self, credentials: Credentials) -> list[ProviderUser]:
        """Directory used to match provider users to chat users by email."""
        ...


@runtime_checkable
class OAuthFlow(Protocol):
    """Implemented by providers offering AuthMode.OAUTH."""

    def authorize_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str: ...

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> OAuthTokens: ...

    async def refresh(self, *, refresh_token: str) -> OAuthTokens: ...


@runtime_checkable
class ChatProvider(Protocol):
    """A chat workspace whose group handles we keep pointed at the on-call person.

    Slack today; Microsoft Teams maps onto the same shape, with Teams tags
    (Graph `teamwork tags`) standing in for Slack user groups.
    """

    kind: str
    display_name: str

    def install_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def complete_install(self, *, code: str, redirect_uri: str) -> ChatInstall: ...

    async def verify(self, credentials: ChatCredentials) -> ProviderHealth: ...

    async def list_groups(self, credentials: ChatCredentials) -> list[GroupRef]: ...

    async def list_channels(self, credentials: ChatCredentials) -> list[ChannelRef]: ...

    async def get_group_members(self, credentials: ChatCredentials, group_id: str) -> list[str]: ...

    async def set_group_members(
        self, credentials: ChatCredentials, group_id: str, member_ids: list[str]
    ) -> None:
        """Replace a group's membership.

        Implementations must reject an empty ``member_ids``: a handle that
        mentions nobody is worse than a stale one.
        """
        ...

    async def find_user_by_email(
        self, credentials: ChatCredentials, email: str
    ) -> ChatUser | None: ...

    async def post_message(
        self,
        credentials: ChatCredentials,
        channel_id: str,
        text: str,
        blocks: list[dict[str, object]] | None = None,
    ) -> MessageRef: ...
