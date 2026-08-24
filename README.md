# On-Call Sync

Keeps a chat group handle pointed at whoever is actually on call.

When someone pages `@devops-on-call` in Slack, the people notified are whoever is
in that user group — a list normally maintained by hand, which goes stale within a
rotation or two. This service maps a **PagerDuty schedule → Slack user group**,
rewrites the group's membership at every handoff, and posts a handoff message to a
channel you choose.

PagerDuty and Slack are the first integrations, not the only ones. All vendor code
sits behind the `OncallProvider` / `ChatProvider` interfaces in `app/domain/` so
Opsgenie and Microsoft Teams can be added without touching the sync engine.

See [`docs/PLAN.md`](docs/PLAN.md) for the full design, milestones and known risks.

## Layout

```
backend/    FastAPI api + ARQ worker (shared app package)
frontend/   React + Vite SPA
docs/       Design plan
```

## Local development

```bash
cp .env.example .env
python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # → CREDENTIAL_KEK
make up          # postgres, redis, api, worker
make migrate     # bootstraps the app role, then applies migrations
make web         # frontend at http://localhost:5173
```

### Two database roles

The app connects as `oncall_app`, a role that is neither a superuser nor the table
owner. That is load-bearing, not hygiene: superusers bypass row-level security
outright and `FORCE ROW LEVEL SECURITY` only reaches the owner, so connecting as
either would leave the tenant-isolation policies doing nothing. `make db-bootstrap`
(run automatically by `make migrate`) creates the role and its grants from
`DATABASE_URL`; `DATABASE_ADMIN_URL` is the owner and is used only for migrations.

API at http://localhost:8000 — `/health`, `/docs`, `/metrics`.

Slack OAuth and the events endpoint need a public URL: run `ngrok http 8000` and
point the Slack app's redirect URI at `<ngrok-url>/api/v1/chat/slack/callback`.

`make test` runs backend tests, `make lint` runs ruff + mypy.

## Status

**M4 — rules and identities.** On top of M1–M3: sync rule CRUD, the email-based
identity resolver with manual override, the rule builder and identities pages,
and the `/preview` dry run.

`sync_rules.evaluate()` answers "who should this handle contain right now, and
when does that change" without writing anything. `/preview` and M5's reconciler
call the same function, so the dry run cannot diverge from what actually happens —
a preview that lied would be worse than no preview.

Two things are load-bearing and tested rather than asserted:

- **Tenant isolation has two independent belts.** The repository layer applies
  `org_id` by construction; Postgres RLS filters anything that skips it.
  `tests/test_tenancy.py` and `tests/test_oncall_api.py` each issue a deliberately
  unscoped `select(...)` and assert only the bound tenant's rows come back.
- **Credentials are envelope-encrypted** with a per-org data key wrapped by the
  environment KEK, and the org id is bound in as AAD — so a ciphertext moved
  between tenants fails to authenticate rather than decrypting to something
  plausible (`tests/test_crypto.py`).

**Slack's user-group write path is worth knowing about.**
`usergroups.users.update` accepts both bot and user tokens, but whether a *bot*
token is permitted depends on the workspace's User Groups permission setting, not
on our app's scopes. So the install requests both a bot grant and a user grant,
and the write path tries the bot token first and falls back to the installer's
token on `permission_denied`. A workspace installed without the user grant is
flagged in the UI, because it has no fallback if that setting is ever tightened.

Two related Slack limits are handled explicitly rather than discovered at the
first failed sync: user groups require a **Standard plan or above**
(`plan_upgrade_required`), and Slack **refuses to leave a user group empty**
(`no_users_provided`) — which is why sync rules will carry a fallback member in M4.

Three rules are enforced where a rule is written rather than discovered at the
first handoff: one rule per user group (two would undo each other every handoff),
a channel the app has actually joined, and a schedule and group that still exist.

When a rule resolves to nobody, it uses its configured fallback member — and if
there is none, it leaves the handle **completely untouched** rather than emptying
it. `/preview` reports `would_write: false` in that case, so it never promises a
change the reconciler will not make.

The sync engine lands in M5.

### Configuring the providers

**Slack.** Set `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` and
`SLACK_SIGNING_SECRET`. In the Slack app config:

```
Redirect URL:  <APP_BASE_URL>/api/v1/chat/slack/callback
Event URL:     <APP_BASE_URL>/api/v1/webhooks/slack/events
Bot scopes:    usergroups:read, usergroups:write, channels:read, groups:read,
               chat:write, users:read, users:read.email, team:read
User scope:    usergroups:write
Events:        app_uninstalled, tokens_revoked, subteam_updated
```

Both URLs need to be publicly reachable — use `ngrok http 8000` in development.

### Configuring PagerDuty OAuth

OAuth is offered only when the deployment has an app registered; otherwise the UI
shows the API-key path alone. Set `PAGERDUTY_CLIENT_ID` and
`PAGERDUTY_CLIENT_SECRET`, and register the redirect URI:

```
<APP_BASE_URL>/api/v1/oncall/connections/pagerduty/oauth/callback
```

Scopes requested are read-only: `schedules.read`, `oncalls.read`, `users.read`.
