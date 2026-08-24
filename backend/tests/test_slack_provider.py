"""The Slack adapter, with emphasis on the user-group write path.

usergroups.users.update accepts both bot and user tokens, but whether a bot token
is *allowed* depends on the workspace's User Groups permission setting. These
tests pin the resulting fallback behaviour, because it is the difference between
the product working and silently failing on a locked-down workspace.
"""

import uuid

import httpx
import pytest
import respx

from app.core.http import ProviderAuthError
from app.domain.types import ChatCredentials
from app.providers.chat.slack.provider import (
    EmptyMembershipRejected,
    GroupWriteNotPermitted,
    SlackProvider,
    UserGroupsUnavailable,
)
from tests.slack_fixtures import API, channel, err, ok, slack_user, usergroup

BOTH_TOKENS = ChatCredentials(org_id=uuid.uuid4(), bot_token="xoxb-bot", user_token="xoxp-user")
BOT_ONLY = ChatCredentials(org_id=uuid.uuid4(), bot_token="xoxb-bot")
UPDATE = f"{API}/usergroups.users.update"


def _sent_token(call: respx.models.Call) -> str:
    return call.request.headers["Authorization"].removeprefix("Bearer ")


@respx.mock
async def test_bot_token_is_used_when_the_workspace_allows_it() -> None:
    route = respx.post(UPDATE).mock(return_value=httpx.Response(200, json=ok()))
    await SlackProvider().set_group_members(BOTH_TOKENS, "S123", ["U1", "U2"])

    assert route.call_count == 1
    assert _sent_token(route.calls[0]) == "xoxb-bot"
    assert "users=U1%2CU2" in route.calls[0].request.content.decode()


@respx.mock
async def test_falls_back_to_the_user_token_when_the_bot_is_denied() -> None:
    """A workspace that restricts user-group management rejects the bot outright."""
    route = respx.post(UPDATE).mock(
        side_effect=[
            httpx.Response(200, json=err("permission_denied")),
            httpx.Response(200, json=ok()),
        ]
    )
    await SlackProvider().set_group_members(BOTH_TOKENS, "S123", ["U1"])

    assert route.call_count == 2
    assert _sent_token(route.calls[0]) == "xoxb-bot"
    assert _sent_token(route.calls[1]) == "xoxp-user"


@respx.mock
async def test_denied_with_no_user_token_gives_an_actionable_error() -> None:
    respx.post(UPDATE).mock(return_value=httpx.Response(200, json=err("permission_denied")))

    with pytest.raises(Exception) as caught:
        await SlackProvider().set_group_members(BOT_ONLY, "S123", ["U1"])
    # No fallback available: surfaces as the Slack error rather than pretending.
    assert "permission_denied" in str(caught.value)


@respx.mock
async def test_denied_for_both_tokens_names_the_workspace_setting() -> None:
    respx.post(UPDATE).mock(return_value=httpx.Response(200, json=err("permission_denied")))

    with pytest.raises(GroupWriteNotPermitted) as caught:
        await SlackProvider().set_group_members(BOTH_TOKENS, "S123", ["U1"])
    assert "Workspace settings" in str(caught.value)


@respx.mock
async def test_empty_membership_is_refused_before_calling_slack() -> None:
    """A handle that mentions nobody is worse than a stale one."""
    route = respx.post(UPDATE).mock(return_value=httpx.Response(200, json=ok()))

    with pytest.raises(EmptyMembershipRejected):
        await SlackProvider().set_group_members(BOTH_TOKENS, "S123", [])
    assert route.call_count == 0


@respx.mock
async def test_slack_rejecting_an_empty_list_is_translated() -> None:
    respx.post(UPDATE).mock(return_value=httpx.Response(200, json=err("no_users_provided")))

    with pytest.raises(EmptyMembershipRejected):
        await SlackProvider().set_group_members(BOTH_TOKENS, "S123", ["U1"])


@respx.mock
async def test_free_plan_workspaces_are_identified() -> None:
    """User groups are Standard-and-above; say so rather than failing obscurely."""
    respx.post(f"{API}/usergroups.list").mock(
        return_value=httpx.Response(200, json=err("plan_upgrade_required"))
    )

    with pytest.raises(UserGroupsUnavailable):
        await SlackProvider().list_groups(BOTH_TOKENS)


@respx.mock
async def test_revoked_token_is_an_auth_error_not_a_retry() -> None:
    route = respx.post(f"{API}/auth.test").mock(
        return_value=httpx.Response(200, json=err("token_revoked"))
    )

    with pytest.raises(ProviderAuthError):
        await SlackProvider().verify(BOTH_TOKENS)
    assert route.call_count == 1


@respx.mock
async def test_list_groups_maps_handles() -> None:
    respx.post(f"{API}/usergroups.list").mock(
        return_value=httpx.Response(
            200,
            json=ok(usergroups=[usergroup("S1", "devops-on-call", "DevOps On-Call")]),
        )
    )
    groups = await SlackProvider().list_groups(BOTH_TOKENS)

    assert groups[0].handle == "devops-on-call"
    assert groups[0].external_id == "S1"
    assert groups[0].is_active is True


@respx.mock
async def test_list_channels_follows_cursor_pagination_and_flags_membership() -> None:
    respx.post(f"{API}/conversations.list").mock(
        side_effect=[
            httpx.Response(
                200,
                json=ok(
                    channels=[channel("C1", "ops")],
                    response_metadata={"next_cursor": "page2"},
                ),
            ),
            httpx.Response(
                200,
                json=ok(
                    channels=[channel("C2", "secret", is_member=False, private=True)],
                    response_metadata={"next_cursor": ""},
                ),
            ),
        ]
    )
    channels = await SlackProvider().list_channels(BOTH_TOKENS)

    assert [c.external_id for c in channels] == ["C1", "C2"]
    # The bot cannot post where it is not a member; surface that in the picker.
    assert channels[0].is_member is True
    assert channels[1].is_member is False
    assert channels[1].is_private is True


@respx.mock
async def test_user_lookup_by_email() -> None:
    respx.post(f"{API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json=ok(user=slack_user("U1", "Ada", "ada@acme.dev")))
    )
    found = await SlackProvider().find_user_by_email(BOTH_TOKENS, "ada@acme.dev")

    assert found is not None
    assert found.external_id == "U1"
    assert found.email == "ada@acme.dev"


@respx.mock
async def test_unknown_email_is_not_an_error() -> None:
    """Someone with no Slack account is an ordinary outcome for identity matching."""
    respx.post(f"{API}/users.lookupByEmail").mock(
        return_value=httpx.Response(200, json=err("users_not_found"))
    )
    assert await SlackProvider().find_user_by_email(BOTH_TOKENS, "ghost@acme.dev") is None


@respx.mock
async def test_get_group_members() -> None:
    respx.post(f"{API}/usergroups.users.list").mock(
        return_value=httpx.Response(200, json=ok(users=["U1", "U2"]))
    )
    assert await SlackProvider().get_group_members(BOTH_TOKENS, "S1") == ["U1", "U2"]


@respx.mock
async def test_post_message_sends_text_as_the_block_fallback() -> None:
    route = respx.post(f"{API}/chat.postMessage").mock(
        return_value=httpx.Response(200, json=ok(channel="C1", ts="1724500000.000100"))
    )
    ref = await SlackProvider().post_message(
        BOTH_TOKENS, "C1", "Ada is on call", [{"type": "section"}]
    )

    body = route.calls.last.request.content.decode()
    assert "text=Ada" in body
    assert "blocks=" in body
    assert ref.ts == "1724500000.000100"
