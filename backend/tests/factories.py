"""Helpers that stand up a fully connected org, with both providers mocked."""

from typing import Any

import httpx
import respx
from httpx import AsyncClient

from tests.conftest import csrf, signup
from tests.pagerduty_fixtures import API as PD_API
from tests.pagerduty_fixtures import schedule, schedules_page
from tests.slack_fixtures import API as SLACK_API
from tests.slack_fixtures import channel, install_response, ok, usergroup


async def connect_pagerduty(client: AsyncClient) -> dict[str, Any]:
    respx.get(f"{PD_API}/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([]) | {"total": 1})
    )
    respx.get(f"{PD_API}/v3/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([]))
    )
    response = await client.post(
        "/api/v1/oncall/connections",
        json={"kind": "pagerduty", "api_key": "pd-secret-key", "display_name": "Acme PD"},
        headers=csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def install_slack(client: AsyncClient) -> dict[str, Any]:
    start = await client.post("/api/v1/chat/slack/install/start", headers=csrf(client))
    assert start.status_code == 200, start.text
    state = httpx.URL(start.json()["install_url"]).params["state"]

    respx.post(f"{SLACK_API}/oauth.v2.access").mock(
        return_value=httpx.Response(200, json=install_response())
    )
    callback = await client.get(f"/api/v1/chat/slack/callback?code=code&state={state}")
    assert "installed=slack" in callback.headers["location"]
    return (await client.get("/api/v1/chat/connections")).json()[0]  # type: ignore[no-any-return]


async def cache_pickers(
    client: AsyncClient,
    oncall_connection_id: str,
    chat_connection_id: str,
    *,
    bot_in_channel: bool = True,
) -> None:
    """Populate the schedule, user-group and channel caches a rule validates against."""
    respx.get(f"{PD_API}/schedules").mock(
        return_value=httpx.Response(
            200, json=schedules_page([schedule("PSCHED1", "Primary", "UTC")])
        )
    )
    respx.get(f"{PD_API}/v3/schedules").mock(
        return_value=httpx.Response(200, json=schedules_page([]))
    )
    await client.get(f"/api/v1/oncall/connections/{oncall_connection_id}/schedules?refresh=true")

    respx.post(f"{SLACK_API}/usergroups.list").mock(
        return_value=httpx.Response(
            200, json=ok(usergroups=[usergroup("S_DEVOPS", "devops-on-call", "DevOps On-Call")])
        )
    )
    await client.get(f"/api/v1/chat/connections/{chat_connection_id}/groups?refresh=true")

    respx.post(f"{SLACK_API}/conversations.list").mock(
        return_value=httpx.Response(
            200,
            json=ok(
                channels=[channel("C_OPS", "ops", is_member=bot_in_channel)],
                response_metadata={"next_cursor": ""},
            ),
        )
    )
    await client.get(f"/api/v1/chat/connections/{chat_connection_id}/channels?refresh=true")


async def connected_org(client: AsyncClient, **signup_kwargs: Any) -> dict[str, str]:
    """Sign up, connect PagerDuty, install Slack and warm the pickers."""
    await signup(client, **signup_kwargs)
    oncall = await connect_pagerduty(client)
    chat = await install_slack(client)
    await cache_pickers(client, oncall["id"], chat["id"])
    respx.reset()
    return {"oncall_connection_id": oncall["id"], "chat_connection_id": chat["id"]}


def rule_payload(ids: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "DevOps on-call",
        "oncall_connection_id": ids["oncall_connection_id"],
        "schedule_external_id": "PSCHED1",
        "escalation_levels": [1],
        "chat_connection_id": ids["chat_connection_id"],
        "group_external_id": "S_DEVOPS",
        "notify_channel_external_id": "C_OPS",
        "notify_on_change": True,
    }
    payload.update(overrides)
    return payload
