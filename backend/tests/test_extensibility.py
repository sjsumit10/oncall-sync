"""Can a brand-new provider pair drive the product unchanged?

The whole architecture bets on "adding a provider is a new adapter, not a change
to the engine". These tests cash that bet: they reconcile real rules through
providers that share no code with Slack or PagerDuty, exercising the scheduler,
the identity resolver, templating, drift repair and the degraded path.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core import crypto
from app.db.models import (
    ChatConnection,
    ChatGroup,
    OncallConnection,
    OncallSchedule,
    Organization,
    RuleStatus,
    RunStatus,
    RunTrigger,
    SyncRule,
)
from app.db.session import SessionLocal, bind_org, set_current_org
from app.domain import registry
from app.domain.errors import GroupWriteNotPermitted
from app.domain.interfaces import ChatProvider, OncallProvider
from app.domain.types import AuthMode, OncallSpan
from app.services import sync_engine
from tests.fake_providers import (
    CHAT_KIND,
    ONCALL_KIND,
    FakeChatProvider,
    FakeOncallProvider,
    chat_user,
    person,
)

NOW = datetime.now(UTC).replace(microsecond=0)
ADA = person("P-ADA", "Ada Lovelace", "ada@acme.dev")
BOB = person("P-BOB", "Bob Bobsson", "bob@acme.dev")


def span(user: object, start_hours: float, end_hours: float | None, level: int = 1) -> OncallSpan:
    return OncallSpan(
        user=user,  # type: ignore[arg-type]
        start=NOW + timedelta(hours=start_hours),
        end=None if end_hours is None else NOW + timedelta(hours=end_hours),
        level=level,
    )


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeOncallProvider, FakeChatProvider]:
    oncall = FakeOncallProvider(people=[ADA, BOB])
    chat = FakeChatProvider(
        users_by_email={
            "ada@acme.dev": chat_user("C-ADA", "Ada", "ada@acme.dev"),
            "bob@acme.dev": chat_user("C-BOB", "Bob", "bob@acme.dev"),
        }
    )
    # One line each, exactly as shipping a real provider would be.
    monkeypatch.setitem(registry.ONCALL_PROVIDERS, ONCALL_KIND, oncall)
    monkeypatch.setitem(registry.CHAT_PROVIDERS, CHAT_KIND, chat)
    return oncall, chat


async def build_rule(**overrides: object) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an org wired to the fake providers. Returns (rule_id, org_id)."""
    async with SessionLocal() as db:
        org = Organization(name="Fake Co", slug=f"fake-{uuid.uuid4().hex[:8]}")
        db.add(org)
        await db.flush()
        await bind_org(db, org.id)

        oncall_connection = OncallConnection(
            org_id=org.id,
            kind=ONCALL_KIND,
            auth_mode=AuthMode.API_KEY,
            display_name="Fake On-Call",
            credentials_enc=await crypto.encrypt(db, org.id, "fake-api-key"),
        )
        chat_connection = ChatConnection(
            org_id=org.id,
            kind=CHAT_KIND,
            external_team_id="TEAM-1",
            team_name="Fake Team",
            bot_token_enc=await crypto.encrypt(db, org.id, "fake-bot-token"),
        )
        db.add_all([oncall_connection, chat_connection])
        await db.flush()

        db.add(
            OncallSchedule(
                org_id=org.id,
                connection_id=oncall_connection.id,
                external_id="SCHED-1",
                name="Rota",
                timezone="UTC",
                synced_at=NOW,
            )
        )
        db.add(
            ChatGroup(
                org_id=org.id,
                chat_connection_id=chat_connection.id,
                external_id="GRP-1",
                handle="fake-on-call",
                name="Fake On-Call",
                synced_at=NOW,
            )
        )

        rule = SyncRule(
            org_id=org.id,
            name="Fake rule",
            oncall_connection_id=oncall_connection.id,
            schedule_external_id="SCHED-1",
            chat_connection_id=chat_connection.id,
            group_external_id="GRP-1",
            notify_channel_external_id="CHAN-1",
            notify_on_change=True,
            **{"escalation_levels": [1], **overrides},  # type: ignore[arg-type]
        )
        db.add(rule)
        await db.commit()
        return rule.id, org.id


async def reconcile(rule_id: uuid.UUID, org_id: uuid.UUID, trigger: RunTrigger) -> RunStatus:
    async with SessionLocal() as db:
        await bind_org(db, org_id)
        rule = await db.get(SyncRule, rule_id)
        assert rule is not None
        run = await sync_engine.reconcile(db, rule, trigger=trigger)
        return run.status


def test_the_fakes_satisfy_the_protocols() -> None:
    """Structural conformance, before any behaviour is exercised."""
    assert isinstance(FakeOncallProvider(), OncallProvider)
    assert isinstance(FakeChatProvider(), ChatProvider)


async def test_a_brand_new_provider_pair_drives_a_full_handoff(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    oncall, chat = providers
    oncall.spans = [span(ADA, -2, 6)]
    rule_id, org_id = await build_rule()

    assert await reconcile(rule_id, org_id, RunTrigger.SCHEDULED) is RunStatus.SUCCESS

    assert chat.groups["GRP-1"] == ["C-ADA"]
    assert len(chat.posted) == 1
    # Mention syntax came from the provider, not from anything Slack-shaped.
    assert "@@C-ADA@@" in chat.posted[0].text
    assert "<@" not in chat.posted[0].text
    assert chat.posted[0].handle == "fake-on-call"


async def test_the_engine_never_touches_the_other_vendor(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    """A rule on these providers must not reach for Slack or PagerDuty at all."""
    import respx

    oncall, chat = providers
    oncall.spans = [span(ADA, -2, 6)]
    rule_id, org_id = await build_rule()

    # respx intercepts every outbound HTTP call; with no routes registered, any
    # attempt to reach a real vendor raises instead of silently succeeding.
    with respx.mock(assert_all_called=False):
        assert await reconcile(rule_id, org_id, RunTrigger.SCHEDULED) is RunStatus.SUCCESS

    assert chat.groups["GRP-1"] == ["C-ADA"]
    assert oncall.calls.count("get_oncall_window") == 1


async def test_a_handoff_between_two_people(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    oncall, chat = providers
    oncall.spans = [span(ADA, -4, 1)]
    rule_id, org_id = await build_rule()
    await reconcile(rule_id, org_id, RunTrigger.SCHEDULED)

    oncall.spans = [span(BOB, -1, 8)]
    assert await reconcile(rule_id, org_id, RunTrigger.SCHEDULED) is RunStatus.SUCCESS

    assert chat.groups["GRP-1"] == ["C-BOB"]
    assert len(chat.posted) == 2
    assert "@@C-BOB@@" in chat.posted[1].text
    assert "Ada Lovelace" not in chat.posted[1].text or "Bob" in chat.posted[1].text


async def test_drift_is_repaired_without_announcing(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    oncall, chat = providers
    oncall.spans = [span(ADA, -2, 6)]
    rule_id, org_id = await build_rule()
    await reconcile(rule_id, org_id, RunTrigger.SCHEDULED)
    assert len(chat.posted) == 1

    chat.groups["GRP-1"] = ["C-INTRUDER"]
    await reconcile(rule_id, org_id, RunTrigger.SCHEDULED)

    assert chat.groups["GRP-1"] == ["C-ADA"]
    assert len(chat.posted) == 1, "a repair is not a handoff"


async def test_nobody_resolving_leaves_the_group_alone(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    oncall, chat = providers
    unknown = person("P-X", "Contractor", "x@vendor.dev")
    oncall.spans = [span(unknown, -1, 6)]
    chat.groups["GRP-1"] = ["C-ADA"]
    rule_id, org_id = await build_rule()

    assert await reconcile(rule_id, org_id, RunTrigger.SCHEDULED) is RunStatus.DEGRADED
    assert chat.groups["GRP-1"] == ["C-ADA"], "never empty a live handle"


async def test_a_provider_refusing_the_write_degrades_the_rule(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    """The engine handles the neutral error, with no knowledge of the vendor."""
    oncall, chat = providers
    oncall.spans = [span(ADA, -2, 6)]
    chat.write_error = GroupWriteNotPermitted("This workspace does not allow it")
    rule_id, org_id = await build_rule()

    assert await reconcile(rule_id, org_id, RunTrigger.SCHEDULED) is RunStatus.DEGRADED

    async with SessionLocal() as db:
        set_current_org(org_id)
        rule = await db.get(SyncRule, rule_id)
    assert rule is not None
    assert rule.status is RuleStatus.DEGRADED
    assert rule.consecutive_failures == 0, "a configuration problem is not a fault"


async def test_a_custom_template_renders_for_a_new_provider(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    oncall, chat = providers
    oncall.spans = [span(ADA, -2, 6)]
    rule_id, org_id = await build_rule(
        message_template="{{ oncall_name }} holds {{ handle }} ({{ oncall_mention }})"
    )

    await reconcile(rule_id, org_id, RunTrigger.SCHEDULED)

    assert chat.posted[0].text == "Ada Lovelace holds fake-on-call (@@C-ADA@@)"


async def test_multi_level_escalation_works_for_a_new_provider(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    oncall, chat = providers
    oncall.spans = [span(ADA, -2, 6, level=1), span(BOB, -2, 6, level=2)]
    rule_id, org_id = await build_rule(escalation_levels=[1, 2])

    await reconcile(rule_id, org_id, RunTrigger.SCHEDULED)

    assert sorted(chat.groups["GRP-1"]) == ["C-ADA", "C-BOB"]


async def test_the_next_wakeup_comes_from_the_new_providers_schedule(
    providers: tuple[FakeOncallProvider, FakeChatProvider],
) -> None:
    """Precise scheduling is interface-level behaviour, not a PagerDuty trick."""
    oncall, _ = providers
    boundary = NOW + timedelta(minutes=2)
    oncall.spans = [span(ADA, -2, 2 / 60), span(BOB, 2 / 60, 8)]
    rule_id, org_id = await build_rule()

    await reconcile(rule_id, org_id, RunTrigger.SCHEDULED)

    async with SessionLocal() as db:
        set_current_org(org_id)
        rule = await db.get(SyncRule, rule_id)
    assert rule is not None and rule.next_run_at is not None
    assert boundary < rule.next_run_at < boundary + timedelta(seconds=45)
