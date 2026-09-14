"""The Microsoft Teams adapter: tag membership diffing, mentions, OAuth."""

import json
import uuid

import httpx
import pytest
import respx

from app.domain.errors import EmptyMembershipRejected, TooManyMembers
from app.domain.types import ChatCredentials
from app.providers.chat.teams import oauth
from app.providers.chat.teams.provider import TeamsProvider
from tests.teams_fixtures import (
    API,
    TOKEN_URL,
    channel,
    graph_user,
    me,
    organization,
    tag,
    tag_member,
    tags_page,
    token_response,
)

CREDS = ChatCredentials(
    org_id=uuid.uuid4(), bot_token="graph-token", resource_id="TEAM1"
)


@respx.mock
async def test_verify_reports_the_signed_in_account() -> None:
    respx.get(f"{API}/me").mock(return_value=httpx.Response(200, json=me()))
    health = await TeamsProvider().verify(CREDS)

    assert health.ok is True
    assert "Ada Lovelace" in health.detail
    assert health.account_label == "ada@acme.dev"


@respx.mock
async def test_list_groups_maps_tags() -> None:
    respx.get(f"{API}/teams/TEAM1/tags").mock(
        return_value=httpx.Response(200, json=tags_page([tag("TAG1", "on-call")]))
    )
    groups = await TeamsProvider().list_groups(CREDS)

    assert [g.external_id for g in groups] == ["TAG1"]
    assert groups[0].handle == "on-call"


@respx.mock
async def test_list_groups_requires_a_selected_team() -> None:
    no_team = ChatCredentials(org_id=uuid.uuid4(), bot_token="t")
    with pytest.raises(Exception, match="No Microsoft Team selected"):
        await TeamsProvider().list_groups(no_team)


@respx.mock
async def test_list_channels_maps_teams_channels() -> None:
    respx.get(f"{API}/teams/TEAM1/channels").mock(
        return_value=httpx.Response(200, json=tags_page([channel("C1", "general")]))
    )
    channels = await TeamsProvider().list_channels(CREDS)

    assert channels[0].external_id == "C1"
    assert channels[0].is_private is False


@respx.mock
async def test_set_group_members_adds_and_removes_the_difference() -> None:
    respx.get(f"{API}/teams/TEAM1/tags/TAG1/members").mock(
        return_value=httpx.Response(
            200, json=tags_page([tag_member("M_STALE", "U_STALE"), tag_member("M_KEEP", "U_KEEP")])
        )
    )
    added = respx.post(f"{API}/teams/TEAM1/tags/TAG1/members").mock(
        return_value=httpx.Response(201, json=tag_member("M_NEW", "U_NEW"))
    )
    removed = respx.delete(f"{API}/teams/TEAM1/tags/TAG1/members/M_STALE").mock(
        return_value=httpx.Response(204)
    )

    await TeamsProvider().set_group_members(CREDS, "TAG1", ["U_KEEP", "U_NEW"])

    assert added.call_count == 1
    assert removed.call_count == 1


@respx.mock
async def test_set_group_members_rejects_empty() -> None:
    with pytest.raises(EmptyMembershipRejected):
        await TeamsProvider().set_group_members(CREDS, "TAG1", [])


@respx.mock
async def test_set_group_members_rejects_over_the_cap() -> None:
    with pytest.raises(TooManyMembers):
        await TeamsProvider().set_group_members(CREDS, "TAG1", [f"U{i}" for i in range(26)])


@respx.mock
async def test_find_user_by_email_filters_on_mail() -> None:
    route = respx.get(f"{API}/users").mock(
        return_value=httpx.Response(200, json=tags_page([graph_user("U1", "Bob", "bob@acme.dev")]))
    )
    user = await TeamsProvider().find_user_by_email(CREDS, "bob@acme.dev")

    assert user is not None
    assert user.external_id == "U1"
    assert "mail eq 'bob@acme.dev'" in route.calls.last.request.url.params["$filter"]


@respx.mock
async def test_find_user_by_email_returns_none_on_no_match() -> None:
    respx.get(f"{API}/users").mock(return_value=httpx.Response(200, json=tags_page([])))
    assert await TeamsProvider().find_user_by_email(CREDS, "nobody@acme.dev") is None


@respx.mock
async def test_post_message_resolves_mention_placeholders() -> None:
    respx.get(f"{API}/users/U1").mock(
        return_value=httpx.Response(200, json=graph_user("U1", "Ada Lovelace", "ada@acme.dev"))
    )
    sent = respx.post(f"{API}/teams/TEAM1/channels/C1/messages").mock(
        return_value=httpx.Response(201, json={"id": "msg-1"})
    )

    provider = TeamsProvider()
    text = f"Handoff to {provider.format_mention('U1')}"
    ref = await provider.post_message(CREDS, "C1", text)

    assert ref.ts == "msg-1"
    body = json.loads(sent.calls.last.request.content.decode())
    assert body["body"]["content"] == 'Handoff to <at id="0">Ada Lovelace</at>'
    assert body["mentions"] == [
        {
            "id": 0,
            "mentionText": "Ada Lovelace",
            "mentioned": {"user": {"id": "U1", "displayName": "Ada Lovelace"}},
        }
    ]


@respx.mock
async def test_post_message_without_mentions_sends_plain_html() -> None:
    sent = respx.post(f"{API}/teams/TEAM1/channels/C1/messages").mock(
        return_value=httpx.Response(201, json={"id": "msg-2"})
    )
    await TeamsProvider().post_message(CREDS, "C1", "No mentions here")

    assert "mentions" not in json.loads(sent.calls.last.request.content.decode())


@respx.mock
async def test_complete_install_captures_tenant_and_refresh_token() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=token_response()))
    respx.get(f"{API}/organization").mock(return_value=httpx.Response(200, json=organization()))

    install = await oauth.complete_install(
        code="c", redirect_uri="https://app/cb", code_verifier="v"
    )

    assert install.external_team_id == "TENANT1"
    assert install.team_name == "Acme Corp"
    assert install.bot_token == "graph-access-token"
    assert install.refresh_token == "graph-refresh-token"
    assert install.token_expires_at is not None


@respx.mock
async def test_refresh_exchanges_the_refresh_token() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json=token_response(access_token="new-token"))
    )
    tokens = await oauth.refresh(refresh_token="old-refresh")

    assert tokens.access_token == "new-token"
    assert "grant_type=refresh_token" in route.calls.last.request.content.decode()
