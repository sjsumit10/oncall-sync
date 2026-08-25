"""Guards on the boundaries the design depends on.

Cheap to run, and they fail loudly the moment someone reaches through a layer —
which is when it is easy to fix rather than six months later.
"""

import ast
import pathlib

from httpx import AsyncClient
from sqlalchemy import text

from app.db.session import get_admin_engine

APP = pathlib.Path(__file__).resolve().parent.parent / "app"

#: The Slack webhook route legitimately verifies Slack's request signature; that
#: route is Slack-specific by definition. Everything else reaches adapters only
#: through the registry and the domain interfaces.
VENDOR_IMPORT_EXCEPTIONS = {"api/v1/webhooks.py", "domain/registry.py"}

#: users carries org_id but is deliberately outside RLS: login resolves a user by
#: email before any tenant is known. The repository layer scopes it instead, and
#: tests/test_tenancy.py covers that path.
RLS_EXEMPT_TABLES = {"users"}


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_business_logic_never_imports_a_vendor_adapter() -> None:
    """The extensibility promise, enforced rather than trusted."""
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if "providers" in path.relative_to(APP).parts or relative in VENDOR_IMPORT_EXCEPTIONS:
            continue
        offenders += [
            f"{relative} imports {module}"
            for module in _imported_modules(path)
            if module.startswith("app.providers.") and module.count(".") > 2
        ]

    assert offenders == [], (
        "Vendor adapters must only be reached through app/domain/registry.py:\n"
        + "\n".join(offenders)
    )


def test_no_vendor_name_appears_in_the_sync_engine() -> None:
    """The engine is where a leak would hurt most, so check the prose too."""
    source = (APP / "services" / "sync_engine.py").read_text().lower()
    for vendor in ("slack", "pagerduty", "opsgenie", "teams"):
        assert vendor not in source, f"sync_engine.py mentions {vendor}"


def _tenant_tables_from_models() -> set[str]:
    """Every mapped table that carries an org_id column."""
    tables: set[str] = set()
    for path in (APP / "db" / "models").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            columns = {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
            table = next(
                (
                    item.value.value
                    for item in node.body
                    if isinstance(item, ast.Assign)
                    and isinstance(item.value, ast.Constant)
                    and any(
                        isinstance(t, ast.Name) and t.id == "__tablename__" for t in item.targets
                    )
                ),
                None,
            )
            if table and "org_id" in columns:
                tables.add(str(table))
    return tables


async def test_every_tenant_table_is_covered_by_row_level_security() -> None:
    """A new org-scoped table must not ship without a policy.

    Asks the database rather than reading the migrations: the database is the
    thing that actually has to be right.
    """
    async with get_admin_engine().connect() as conn:
        protected = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT tablename FROM pg_policies WHERE policyname = 'org_isolation'")
                )
            ).all()
        }
        forced = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity"
                    )
                )
            ).all()
        }

    expected = _tenant_tables_from_models() - RLS_EXEMPT_TABLES
    assert sorted(expected - protected) == [], "tenant tables with no org_isolation policy"
    # FORCE matters as much as the policy: without it the table owner bypasses it,
    # which is exactly the bug found in M1.
    assert sorted(expected - forced) == [], "tenant tables where RLS is not forced"


DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"


def _manifest_from_setup_doc() -> dict:
    import re

    import yaml

    text = (DOCS / "SETUP.md").read_text()
    block = re.search(r"```yaml\n(.*?)```", text, re.S)
    assert block, "SETUP.md no longer contains a Slack app manifest"
    return dict(yaml.safe_load(block.group(1)))


def test_the_documented_slack_manifest_matches_the_code() -> None:
    """Setup docs rot silently. This one cannot.

    If someone adds a scope the adapter needs, the manifest people paste into
    Slack has to gain it too — otherwise the app installs and then fails at the
    first call that needs it.
    """
    from app.providers.chat.slack.oauth import BOT_SCOPES, USER_SCOPES

    manifest = _manifest_from_setup_doc()
    scopes = manifest["oauth_config"]["scopes"]

    assert set(scopes["bot"]) == set(BOT_SCOPES)
    assert set(scopes["user"]) == set(USER_SCOPES)


def test_the_documented_slack_events_match_what_the_webhook_handles() -> None:
    from app.api.v1.webhooks import REVOCATION_EVENTS

    subscribed = set(_manifest_from_setup_doc()["settings"]["event_subscriptions"]["bot_events"])

    assert REVOCATION_EVENTS <= subscribed, "the app would never hear about a revoked token"
    # The free drift signal: without it, a hand-edited group waits for the
    # periodic reconcile instead of being repaired immediately.
    assert "subteam_updated" in subscribed


def test_the_documented_pagerduty_scopes_match_the_code() -> None:
    from app.providers.oncall.pagerduty.oauth import DEFAULT_SCOPES

    text = (DOCS / "SETUP.md").read_text()
    for scope in DEFAULT_SCOPES:
        assert scope in text, f"SETUP.md does not mention the {scope} scope"


async def test_the_documented_callback_urls_are_real_routes(client: AsyncClient) -> None:
    """A wrong redirect URL in the docs is a support ticket every single time.

    Asserted by making the request rather than introspecting the router: what
    matters is that the URL people paste into Slack and PagerDuty resolves.
    """
    text = (DOCS / "SETUP.md").read_text()
    for url in (
        "/api/v1/chat/slack/callback",
        "/api/v1/webhooks/slack/events",
        "/api/v1/oncall/connections/pagerduty/oauth/callback",
    ):
        assert url in text, f"SETUP.md no longer documents {url}"
        # 302 (handled redirect) or 405 (POST-only) both prove it exists;
        # 404 would mean the docs point somewhere that is not there.
        assert (await client.get(url)).status_code != 404, f"{url} is not a route"
