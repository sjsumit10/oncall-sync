"""Microsoft Teams adapter for the ChatProvider interface."""

import json
import re
from typing import Any

import httpx

from app.core.http import ProviderAuthError
from app.domain.errors import EmptyMembershipRejected, TooManyMembers
from app.domain.types import (
    Announcement,
    ChannelRef,
    ChatCredentials,
    ChatInstall,
    ChatUser,
    GroupRef,
    MessageRef,
    OAuthTokens,
    ProviderHealth,
)
from app.providers.chat.teams import cards, oauth
from app.providers.chat.teams.client import GraphClient

#: Graph's own limit on how many members one tag may hold.
MAX_TAG_MEMBERS = 25

#: What format_mention() embeds and post_message() later resolves — the raw
#: Graph user id, not yet a real Teams <at> mention (that needs a small
#: sequential index and a display name, both only known once every mention in
#: the message has been collected).
_MENTION_RE = re.compile(r'<at id="([^"]+)">[^<]*</at>')


def _to_group(tag: dict[str, Any]) -> GroupRef:
    name = tag.get("displayName") or tag["id"]
    return GroupRef(external_id=tag["id"], handle=name, name=name, is_active=True)


def _to_channel(channel: dict[str, Any]) -> ChannelRef:
    return ChannelRef(
        external_id=channel["id"],
        name=channel.get("displayName", ""),
        is_private=channel.get("membershipType") == "private",
        # Graph doesn't expose "has the app joined this channel" the way
        # Slack does; a delegated user token can post to any channel the
        # installing admin can see, so treat every listed channel as postable.
        is_member=True,
    )


def _to_user(user: dict[str, Any]) -> ChatUser:
    return ChatUser(
        external_id=user["id"],
        name=user.get("displayName") or user.get("mail") or user["id"],
        email=user.get("mail"),
    )


class TeamsProvider:
    kind: str = "teams"
    display_name: str = "Microsoft Teams"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _api(self, credentials: ChatCredentials) -> GraphClient:
        return GraphClient(credentials.bot_token, client=self._client)

    def _team_id(self, credentials: ChatCredentials) -> str:
        if not credentials.resource_id:
            raise ProviderAuthError("No Microsoft Team selected for this connection yet")
        return credentials.resource_id

    def install_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str:
        return oauth.install_url(
            state=state, redirect_uri=redirect_uri, code_challenge=code_challenge
        )

    async def complete_install(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> ChatInstall:
        return await oauth.complete_install(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )

    async def refresh(self, *, refresh_token: str) -> OAuthTokens:
        return await oauth.refresh(refresh_token=refresh_token)

    async def verify(self, credentials: ChatCredentials) -> ProviderHealth:
        api = self._api(credentials)
        try:
            me = await api.call("GET", "/me")
        finally:
            await api.aclose()
        return ProviderHealth(
            ok=True,
            detail=f"Connected as {me.get('displayName', 'a Microsoft account')}",
            account_label=me.get("userPrincipalName"),
        )

    async def list_available_teams(self, credentials: ChatCredentials) -> list[dict[str, str]]:
        """The installing admin's joined Teams, for the post-install "pick a
        Team to connect" step. Not part of the ChatProvider protocol — this is
        Teams-specific (a tenant can contain many Teams; Slack's connection
        already *is* the one workspace, so there is nothing to pick there)."""
        api = self._api(credentials)
        try:
            teams = [item async for item in api.paginate("/me/joinedTeams", "value")]
        finally:
            await api.aclose()
        return [{"id": t["id"], "name": t.get("displayName") or t["id"]} for t in teams]

    async def list_groups(self, credentials: ChatCredentials) -> list[GroupRef]:
        api = self._api(credentials)
        try:
            return [
                _to_group(item)
                async for item in api.paginate(f"/teams/{self._team_id(credentials)}/tags", "value")
            ]
        finally:
            await api.aclose()

    async def list_channels(self, credentials: ChatCredentials) -> list[ChannelRef]:
        api = self._api(credentials)
        try:
            return [
                _to_channel(item)
                async for item in api.paginate(
                    f"/teams/{self._team_id(credentials)}/channels", "value"
                )
            ]
        finally:
            await api.aclose()

    async def get_group_members(self, credentials: ChatCredentials, group_id: str) -> list[str]:
        api = self._api(credentials)
        try:
            members = [
                item
                async for item in api.paginate(
                    f"/teams/{self._team_id(credentials)}/tags/{group_id}/members", "value"
                )
            ]
        finally:
            await api.aclose()
        return [str(m["userId"]) for m in members]

    async def set_group_members(
        self, credentials: ChatCredentials, group_id: str, member_ids: list[str]
    ) -> None:
        """Diff and reconcile membership one add/remove call at a time.

        Graph has no "replace the whole list" call for tags the way Slack's
        usergroups.users.update does — membership is individual
        teamworkTagMember resources.
        """
        if not member_ids:
            raise EmptyMembershipRejected("Refusing to empty a tag")
        if len(member_ids) > MAX_TAG_MEMBERS:
            raise TooManyMembers(
                f"A Teams tag can hold at most {MAX_TAG_MEMBERS} members, got {len(member_ids)}"
            )

        team_id = self._team_id(credentials)
        api = self._api(credentials)
        try:
            current = {
                str(item["userId"]): item["id"]
                async for item in api.paginate(
                    f"/teams/{team_id}/tags/{group_id}/members", "value"
                )
            }
            desired = set(member_ids)

            for user_id in desired - current.keys():
                await api.call(
                    "POST",
                    f"/teams/{team_id}/tags/{group_id}/members",
                    json={"userId": user_id},
                )
            for user_id in current.keys() - desired:
                await api.call(
                    "DELETE", f"/teams/{team_id}/tags/{group_id}/members/{current[user_id]}"
                )
        finally:
            await api.aclose()

    async def find_user_by_email(
        self, credentials: ChatCredentials, email: str
    ) -> ChatUser | None:
        api = self._api(credentials)
        try:
            payload = await api.call("GET", "/users", params={"$filter": f"mail eq '{email}'"})
        finally:
            await api.aclose()
        matches = payload.get("value") or []
        return _to_user(matches[0]) if matches else None

    async def post_message(
        self,
        credentials: ChatCredentials,
        channel_id: str,
        text: str,
        blocks: list[dict[str, object]] | None = None,
    ) -> MessageRef:
        content, mentions = await self._resolve_mentions(credentials, text)
        attachments = blocks or []
        # A card attachment only renders where the body references it.
        if attachments:
            refs = "".join(f'<attachment id="{a["id"]}"></attachment>' for a in attachments)
            content = f"{content}{refs}"

        body: dict[str, Any] = {"body": {"contentType": "html", "content": content}}
        if mentions:
            body["mentions"] = mentions
        if attachments:
            # Graph wants each attachment's card body JSON-encoded as a string,
            # not the raw dict render_announcement built it as.
            body["attachments"] = [
                {**a, "content": json.dumps(a["content"])} for a in attachments
            ]

        api = self._api(credentials)
        try:
            sent = await api.call(
                "POST",
                f"/teams/{self._team_id(credentials)}/channels/{channel_id}/messages",
                json=body,
            )
        finally:
            await api.aclose()
        return MessageRef(channel_id=channel_id, ts=str(sent.get("id", "")))

    async def _resolve_mentions(
        self, credentials: ChatCredentials, text: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """Turn format_mention()'s placeholder <at> tags into Graph's real
        shape: a sequential index in the HTML plus a matching mentions[] entry
        carrying the mentioned user's display name."""
        user_ids = list(dict.fromkeys(_MENTION_RE.findall(text)))
        if not user_ids:
            return text, []

        api = self._api(credentials)
        try:
            names: dict[str, str] = {}
            for user_id in user_ids:
                user = await api.call("GET", f"/users/{user_id}")
                names[user_id] = str(user.get("displayName") or user_id)
        finally:
            await api.aclose()

        mentions: list[dict[str, Any]] = []
        content = text
        for index, user_id in enumerate(user_ids):
            name = names[user_id]
            content = content.replace(
                f'<at id="{user_id}">{user_id}</at>', f'<at id="{index}">{name}</at>'
            )
            mentions.append(
                {
                    "id": index,
                    "mentionText": name,
                    "mentioned": {"user": {"id": user_id, "displayName": name}},
                }
            )
        return content, mentions

    def format_mention(self, chat_user_id: str) -> str:
        """A placeholder <at> tag; post_message() resolves it to the real
        Graph mention shape (sequential id + a sibling mentions[] entry)."""
        return f'<at id="{chat_user_id}">{chat_user_id}</at>'

    def render_announcement(
        self, announcement: Announcement
    ) -> tuple[str, list[dict[str, object]]]:
        card = cards.build(announcement)
        attachment: dict[str, object] = {
            "id": "1",
            "contentType": cards.ADAPTIVE_CARD_CONTENT_TYPE,
            "content": card,
        }
        return cards.notification_text(announcement), [attachment]

    async def post_announcement(
        self, credentials: ChatCredentials, channel_id: str, announcement: Announcement
    ) -> MessageRef:
        text, blocks = self.render_announcement(announcement)
        return await self.post_message(credentials, channel_id, text, blocks)
