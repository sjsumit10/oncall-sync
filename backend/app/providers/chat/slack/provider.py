"""Slack adapter for the ChatProvider interface."""

import json
from typing import Any

import httpx
import structlog
from redis.asyncio import Redis

from app.core.http import ProviderAuthError
from app.domain.types import (
    ChannelRef,
    ChatCredentials,
    ChatInstall,
    ChatUser,
    GroupRef,
    MessageRef,
    ProviderHealth,
)
from app.providers.chat.slack import oauth
from app.providers.chat.slack.client import (
    EMPTY_MEMBERSHIP_ERRORS,
    PERMISSION_DENIED,
    PLAN_UPGRADE_REQUIRED,
    SlackApiError,
    SlackClient,
)

log = structlog.get_logger(__name__)


class GroupWriteNotPermitted(RuntimeError):
    """Neither the bot nor the installing user may manage this workspace's groups."""


class UserGroupsUnavailable(RuntimeError):
    """User groups are a Standard-and-above Slack feature."""


class EmptyMembershipRejected(RuntimeError):
    """Slack refuses to leave a user group with no members."""


def _to_group(payload: dict[str, Any]) -> GroupRef:
    return GroupRef(
        external_id=payload["id"],
        handle=payload.get("handle") or payload.get("name", ""),
        name=payload.get("name") or payload.get("handle", ""),
        is_active=payload.get("date_delete", 0) in (0, None),
    )


def _to_channel(payload: dict[str, Any]) -> ChannelRef:
    return ChannelRef(
        external_id=payload["id"],
        name=payload.get("name", ""),
        is_private=bool(payload.get("is_private")),
        # Slack only delivers messages to channels the bot has joined.
        is_member=bool(payload.get("is_member")),
    )


def _to_user(payload: dict[str, Any]) -> ChatUser:
    profile = payload.get("profile") or {}
    return ChatUser(
        external_id=payload["id"],
        name=profile.get("display_name") or payload.get("real_name") or payload.get("name", ""),
        email=profile.get("email"),
        is_bot=bool(payload.get("is_bot")),
    )


class SlackProvider:
    kind: str = "slack"
    display_name: str = "Slack"

    def __init__(
        self, *, client: httpx.AsyncClient | None = None, redis: Redis | None = None
    ) -> None:
        self._client = client
        self._redis = redis

    def _api(self, credentials: ChatCredentials, *, as_user: bool = False) -> SlackClient:
        token = credentials.user_token if as_user else credentials.bot_token
        if token is None:
            raise ProviderAuthError("No Slack user token stored for this workspace")
        return SlackClient(
            token, org_id=str(credentials.org_id), client=self._client, redis=self._redis
        )

    def install_url(self, *, state: str, redirect_uri: str) -> str:
        return oauth.install_url(state=state, redirect_uri=redirect_uri)

    async def complete_install(self, *, code: str, redirect_uri: str) -> ChatInstall:
        return await oauth.complete_install(code=code, redirect_uri=redirect_uri)

    async def verify(self, credentials: ChatCredentials) -> ProviderHealth:
        api = self._api(credentials)
        try:
            payload = await api.call("auth.test")
        finally:
            await api.aclose()
        return ProviderHealth(
            ok=True,
            detail=f"Connected to {payload.get('team', 'Slack')}",
            account_label=payload.get("team_id"),
        )

    async def list_groups(self, credentials: ChatCredentials) -> list[GroupRef]:
        api = self._api(credentials)
        try:
            payload = await api.call("usergroups.list", {"include_disabled": "false"})
        except SlackApiError as exc:
            if exc.error == PLAN_UPGRADE_REQUIRED:
                raise UserGroupsUnavailable(
                    "Slack user groups require a Standard plan or above"
                ) from exc
            raise
        finally:
            await api.aclose()
        return [_to_group(item) for item in payload.get("usergroups", [])]

    async def list_channels(self, credentials: ChatCredentials) -> list[ChannelRef]:
        api = self._api(credentials)
        try:
            return [
                _to_channel(item)
                async for item in api.paginate(
                    "conversations.list",
                    "channels",
                    {"types": "public_channel,private_channel", "exclude_archived": "true"},
                )
            ]
        finally:
            await api.aclose()

    async def get_group_members(self, credentials: ChatCredentials, group_id: str) -> list[str]:
        api = self._api(credentials)
        try:
            payload = await api.call("usergroups.users.list", {"usergroup": group_id})
        finally:
            await api.aclose()
        return list(payload.get("users", []))

    async def set_group_members(
        self, credentials: ChatCredentials, group_id: str, member_ids: list[str]
    ) -> None:
        """Replace a user group's membership.

        Tries the bot token first and falls back to the installing user's token,
        because a workspace that restricts User Groups management to admins
        rejects the bot with permission_denied no matter which scopes we hold.
        """
        if not member_ids:
            # Slack rejects this outright, and a handle that pages nobody is
            # worse than a stale one. Callers must supply a fallback member.
            raise EmptyMembershipRejected("Refusing to empty a user group")

        params = {"usergroup": group_id, "users": ",".join(member_ids)}
        try:
            await self._write(credentials, params, as_user=False)
            return
        except SlackApiError as exc:
            if exc.error != PERMISSION_DENIED or credentials.user_token is None:
                raise self._translate(exc) from exc
            log.info("slack.usergroup_write_falling_back_to_user_token", group_id=group_id)

        try:
            await self._write(credentials, params, as_user=True)
        except SlackApiError as exc:
            if exc.error == PERMISSION_DENIED:
                raise GroupWriteNotPermitted(
                    "This workspace restricts who may manage user groups. Reinstall as a "
                    "workspace admin, or allow everyone to manage user groups under "
                    "Settings & administration > Workspace settings > Permissions."
                ) from exc
            raise self._translate(exc) from exc

    async def _write(
        self, credentials: ChatCredentials, params: dict[str, Any], *, as_user: bool
    ) -> None:
        api = self._api(credentials, as_user=as_user)
        try:
            await api.call("usergroups.users.update", params, write=True)
        finally:
            await api.aclose()

    @staticmethod
    def _translate(exc: SlackApiError) -> Exception:
        if exc.error == PLAN_UPGRADE_REQUIRED:
            return UserGroupsUnavailable("Slack user groups require a Standard plan or above")
        if exc.error in EMPTY_MEMBERSHIP_ERRORS:
            return EmptyMembershipRejected("Slack rejected an empty user group")
        return exc

    async def find_user_by_email(self, credentials: ChatCredentials, email: str) -> ChatUser | None:
        api = self._api(credentials)
        try:
            payload = await api.call("users.lookupByEmail", {"email": email})
        except SlackApiError as exc:
            # A person with no Slack account is an ordinary outcome, not a failure.
            if exc.error == "users_not_found":
                return None
            raise
        finally:
            await api.aclose()
        return _to_user(payload["user"])

    async def post_message(
        self,
        credentials: ChatCredentials,
        channel_id: str,
        text: str,
        blocks: list[dict[str, object]] | None = None,
    ) -> MessageRef:
        api = self._api(credentials)
        try:
            payload = await api.call(
                "chat.postMessage",
                {
                    "channel": channel_id,
                    # Also the notification and accessibility fallback for blocks.
                    "text": text,
                    "blocks": json.dumps(blocks) if blocks else None,
                },
            )
        finally:
            await api.aclose()
        return MessageRef(channel_id=payload.get("channel", channel_id), ts=payload.get("ts", ""))
