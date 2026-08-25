"""Template editing and the rendered handoff message end to end."""

from urllib.parse import parse_qs

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import get_settings
from tests.conftest import csrf
from tests.factories import connected_org, rule_payload
from tests.pagerduty_fixtures import API as PD_API
from tests.pagerduty_fixtures import oncall, oncalls_page
from tests.slack_fixtures import API as SLACK_API
from tests.slack_fixtures import ok, slack_user

RULES = "/api/v1/rules"
PREVIEW = f"{RULES}/template/preview"


@pytest.fixture(autouse=True)
def provider_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "slack-client-id")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-client-secret"))


def posted(route: respx.Route) -> dict[str, str]:
    body = parse_qs(route.calls.last.request.content.decode())
    return {key: value[0] for key, value in body.items()}


async def run_handoff(client: AsyncClient, rule_id: str) -> respx.Route:
    """Sync twice so the second run is a genuine change of person."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC).replace(microsecond=0)

    def stamp(hours: int) -> str:
        return (now + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    respx.post(f"{SLACK_API}/users.lookupByEmail").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=ok(
                user=slack_user("U_ADA", "Ada Lovelace", "ada@acme.dev")
                if b"ada" in request.content
                else slack_user("U_BOB", "Bob Bobsson", "bob@acme.dev")
            ),
        )
    )
    respx.post(f"{SLACK_API}/usergroups.users.update").mock(
        return_value=httpx.Response(200, json=ok())
    )

    respx.get(f"{PD_API}/oncalls").mock(
        return_value=httpx.Response(
            200,
            json=oncalls_page([oncall("PU1", "Ada", "ada@acme.dev", stamp(-4), stamp(2))]),
        )
    )
    respx.post(f"{SLACK_API}/usergroups.users.list").mock(
        return_value=httpx.Response(200, json=ok(users=[]))
    )
    post = respx.post(f"{SLACK_API}/chat.postMessage").mock(
        return_value=httpx.Response(200, json=ok(channel="C_OPS", ts="1.1"))
    )
    await client.post(f"{RULES}/{rule_id}/sync", headers=csrf(client))

    respx.get(f"{PD_API}/oncalls").mock(
        return_value=httpx.Response(
            200,
            # Bob's shift must cover *now*, otherwise nobody is on call.
            json=oncalls_page([oncall("PU2", "Bob", "bob@acme.dev", stamp(-1), stamp(8))]),
        )
    )
    respx.post(f"{SLACK_API}/usergroups.users.list").mock(
        return_value=httpx.Response(200, json=ok(users=["U_ADA"]))
    )
    await client.post(f"{RULES}/{rule_id}/sync", headers=csrf(client))
    return post


@respx.mock
async def test_preview_renders_the_default_template(client: AsyncClient) -> None:
    await connected_org(client)
    response = await client.post(PREVIEW, json={}, headers=csrf(client))

    assert response.status_code == 200, response.text
    body = response.json()
    assert "<@U024BE7LH> is now on call" in body["text"]
    assert body["problems"] == []
    assert body["blocks"][0]["type"] == "section"
    assert "oncall_mention" in body["variables"]


@respx.mock
async def test_preview_renders_a_custom_template(client: AsyncClient) -> None:
    await connected_org(client)
    response = await client.post(
        PREVIEW,
        json={"template": ":rotating_light: {{ oncall_name }} has {{ handle }}"},
        headers=csrf(client),
    )

    assert response.json()["text"] == ":rotating_light: Ada Lovelace has devops-on-call"


@respx.mock
async def test_preview_reports_an_unknown_variable_without_rendering(
    client: AsyncClient,
) -> None:
    await connected_org(client)
    response = await client.post(
        PREVIEW, json={"template": "Paging {{ oncall_manager }}"}, headers=csrf(client)
    )

    body = response.json()
    assert body["text"] == ""
    assert "oncall_manager" in body["problems"][0]


@respx.mock
async def test_a_rule_cannot_be_saved_with_a_broken_template(client: AsyncClient) -> None:
    ids = await connected_org(client)
    response = await client.post(
        RULES,
        json=rule_payload(ids, message_template="Hi {{ nope }}"),
        headers=csrf(client),
    )

    assert response.status_code == 400
    assert "nope" in response.json()["detail"]
    assert (await client.get(RULES)).json() == []


@respx.mock
async def test_a_template_cannot_be_broken_by_an_update(client: AsyncClient) -> None:
    ids = await connected_org(client)
    created = (await client.post(RULES, json=rule_payload(ids), headers=csrf(client))).json()

    response = await client.patch(
        f"{RULES}/{created['id']}",
        json={"message_template": "{% for x in [1] %}{{ x }}{% endfor %}"},
        headers=csrf(client),
    )
    assert response.status_code == 400
    assert "Loops" in response.json()["detail"]


@respx.mock
async def test_the_handoff_message_uses_block_kit(client: AsyncClient) -> None:
    ids = await connected_org(client)
    rule = (await client.post(RULES, json=rule_payload(ids), headers=csrf(client))).json()

    post = await run_handoff(client, rule["id"])
    body = posted(post)

    assert "blocks" in body
    assert '"type": "section"' in body["blocks"]
    # The plain text must stand alone: it is the notification and the a11y path.
    assert "<@U_BOB>" in body["text"]
    assert "Primary" in body["text"]


@respx.mock
async def test_a_custom_template_is_what_gets_posted(client: AsyncClient) -> None:
    ids = await connected_org(client)
    rule = (
        await client.post(
            RULES,
            json=rule_payload(
                ids,
                message_template="{{ oncall_mention }} takes over from {{ previous_name }}",
            ),
            headers=csrf(client),
        )
    ).json()

    post = await run_handoff(client, rule["id"])
    text = posted(post)["text"]

    assert text.startswith("<@U_BOB> takes over from")
    assert "U_ADA" in text


@respx.mock
async def test_a_template_that_fails_at_render_time_still_updates_the_handle(
    client: AsyncClient,
) -> None:
    """The message is the nice-to-have; the handle pointing at the right person is not."""
    ids = await connected_org(client)
    rule = (await client.post(RULES, json=rule_payload(ids), headers=csrf(client))).json()

    # Slip past save-time validation to simulate a template that breaks later.
    from sqlalchemy import text as sql_text

    from app.db.session import get_admin_engine

    async with get_admin_engine().begin() as conn:
        await conn.execute(
            sql_text("UPDATE sync_rules SET message_template = :t WHERE id = :id"),
            {"t": "{{ oncall_name / 0 }}", "id": rule["id"]},
        )

    post = await run_handoff(client, rule["id"])
    runs = (await client.get(f"{RULES}/{rule['id']}/runs")).json()
    latest = runs[0]

    assert latest["new_members"] == ["U_BOB"], "membership must still be correct"
    assert any("failed to render" in problem for problem in latest["problems"])
    # And a usable default went out rather than nothing.
    assert "<@U_BOB> is now on call" in posted(post)["text"]
