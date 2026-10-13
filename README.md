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

## Getting started

[`docs/SETUP.md`](docs/SETUP.md) is the full walkthrough: running the stack,
registering the Slack app (there is a manifest to paste) and the PagerDuty OAuth
app, wiring your first rule, and verifying a real handoff with a PagerDuty
override. Start there.

The quick version follows.

## Local development

Either way, start with the environment file:

```bash
cp .env.example .env
python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# paste that into CREDENTIAL_KEK= in .env
```

`CREDENTIAL_KEK` has no default. The stack starts happily without it and then
refuses the first PagerDuty or Slack connection, so set it now rather than
debugging it later. Keep it: it wraps every stored credential, and losing it
means reconnecting every integration.

There are two ways to run the stack. **Native is the better one for day-to-day
work** — a debugger attaches to a normal local process, restarts are instant, and
the traceback you get is the one your editor can jump into. Everything in docker
is the closer match to production and the fewer moving parts to install.

### Option A — Postgres and Redis in docker, app natively (recommended)

Only the two stateful services run in containers; the API, the worker and the
frontend run on the host.

```bash
make install     # backend/.venv + frontend/node_modules  (once)
make db-up       # postgres + redis only
make migrate-native
```

Then three terminals, one process each:

```bash
make api         # http://localhost:8000  — /health, /docs, /metrics
make worker      # the reconciler; metrics on :9100
make web         # http://localhost:5173
```

Open http://localhost:5173. Vite proxies `/api` to `localhost:8000`, which keeps
the session cookie first-party — so use the Vite origin, not the API's.

`make install` needs **Python 3.12+** and **Node 20+**; both `make api` and
`make worker` reload on save, so leave them running.

**The one thing that catches people.** `DATABASE_URL` and `REDIS_URL` in `.env`
are ignored under docker compose (it substitutes container hostnames) but are
exactly what the native processes use. If you changed `POSTGRES_PORT` or
`REDIS_PORT` because something already had 5432 or 6379, change these to match:

```bash
POSTGRES_PORT=55432
REDIS_PORT=56379
DATABASE_URL=postgresql+asyncpg://oncall_app:oncall_app@localhost:55432/oncall
DATABASE_ADMIN_URL=postgresql+asyncpg://oncall:oncall@localhost:55432/oncall
REDIS_URL=redis://localhost:56379/0
```

A wrong port here surfaces as a connection refused at startup, which is at least
loud. A wrong *role* does not — see the two roles below.

Running the API somewhere other than `:8000`? Point the frontend at it with
`VITE_API_PROXY=http://localhost:8001 make web`.

### Option B — everything in docker

```bash
make up          # postgres, redis, api, worker
make migrate     # bootstraps the app role, then applies migrations
make web         # frontend still runs natively
```

`make logs` tails the API and worker. The frontend has no container: Vite's dev
server wants to be on the host either way.

### Running the tests

Tests always run natively, whichever option you chose, and need `backend/.venv`:

```bash
make test        # backend
make lint        # ruff + mypy --strict
cd frontend && npm test
```

The backend suite uses the containers, so `make db-up` (or `make up`) has to be
running. It connects to a **separate `oncall_test` database** — it truncates every
table between tests, which would be an unwelcome surprise against your
development data — and to Redis db 15. Postgres creates that database on first
boot; if your volume predates this, `make test-db` adds it.

Ports come from `POSTGRES_PORT` / `REDIS_PORT` in `.env`, the same as everything
else, so a remapped port needs no second edit.

### Two database roles

The app connects as `oncall_app`, a role that is neither a superuser nor the table
owner. That is load-bearing, not hygiene: superusers bypass row-level security
outright and `FORCE ROW LEVEL SECURITY` only reaches the owner, so connecting as
either would leave the tenant-isolation policies doing nothing. `make db-bootstrap`
(run automatically by `make migrate`) creates the role and its grants from
`DATABASE_URL`; `DATABASE_ADMIN_URL` is the owner and is used only for migrations.

Slack OAuth and the events endpoint need a public URL: run `ngrok http 8000` and
point the Slack app's redirect URI at `<ngrok-url>/api/v1/chat/slack/callback`.
This is identical in both options — ngrok points at the host port either way.

## Status

**M8 — hardening. All eight milestones are complete.** The security review,
scale checks and the extensibility proof are in place.

**The extensibility proof.** `tests/fake_providers.py` implements an on-call
provider and a chat provider from scratch against the interfaces, sharing no code
with the Slack or PagerDuty adapters. `tests/test_extensibility.py` reconciles
real rules through that pair — handoffs, drift repair, the degraded path,
multi-level escalation, custom templates and precise scheduling — with **no
changes to the engine, services, API or database layer**. Registering a provider
is one line per registry.

Three architectural guards keep it that way: business logic may not import a
vendor adapter, the sync engine may not so much as mention a vendor by name, and
every model carrying `org_id` must have a forced RLS policy in the database.

`sync_rules.evaluate()` answers "who should this handle contain right now, and
when does that change" without writing anything. `/preview`, "Sync now" and the
scheduler all call the same function, so a dry run cannot diverge from what
actually happens.

Two distinctions carry most of the correctness:

- **Writing vs announcing.** Membership is rewritten whenever the chat workspace
  disagrees with the rule — including when a human hand-edited the group. A
  message is posted only when the *on-call people actually changed*. Repairing
  drift must never fabricate a handoff in the channel.
- **Degraded vs failed.** A rule that resolves to nobody has not failed; it has
  nothing safe to write. It leaves the handle exactly as it is, because a stale
  handle still pages a human and an empty one pages no one.

### How scheduling works

Postgres holds the clock. Every rule carries `next_run_at`; a beat tick claims due
rules with `FOR UPDATE SKIP LOCKED` and leases them, so two workers never get the
same rule and a worker that dies mid-run does not strand it. Delayed jobs never
live only in Redis — losing Redis costs at most one tick.

The on-call window fetch already reveals the next shift boundary, so a rule wakes
at the handoff instead of polling; the 5-minute reconcile is the safety net for
retroactive overrides, schedule edits and manual drift.

Claiming spans tenants — that is what a scheduler is — so it runs on the
privileged admin connection while everything downstream binds an org and works
under RLS like any request. The worker refuses to start if that role cannot bypass
RLS, because the alternative failure mode is a scheduler that silently sees
nothing and never fires a handoff while looking perfectly healthy.

`next_run_at` is written as SQL `now()` rather than the app server's clock: the
scheduler compares against the database's clock, and skew between the two would
leave a due rule unclaimed.

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

### Message templates

Templates are user-written, so they render in a Jinja sandbox against a fixed
variable allowlist. Loops, attribute access, subscripting and function calls are
refused **when the template is saved** — a one-line handoff notice needs none of
them, which makes the sandbox a second line of defence rather than the only one,
and turns `{{ ''.__class__ }}` into a save-time error instead of a silent blank.

Rendering is deliberately non-fatal: if a template fails at run time the handle is
still updated and the built-in default is sent instead, with the problem recorded
on the run. A typo in a message must never stop the group from pointing at the
right person.

Mention syntax comes from the chat provider rather than the engine — only the
adapter knows what actually notifies someone on its platform — and the same
`render_announcement` the engine posts through is what the editor previews, so
the preview is exactly what would be sent.

### Metrics

Scrape **two** targets: the API on `/metrics`, and the worker on
`WORKER_METRICS_PORT` (9100). The worker does nearly all the reconciling, so its
counters are the ones that matter; the API is where the fleet gauges live, read at
scrape time so a restarted process reports the truth rather than zeros.

`oncall_handoff_lag_seconds` is the SLI — how long after a shift actually changed
did the handle catch up. It deliberately counts **only** scheduled runs that moved
the membership between two known states. A manual "Sync now", a first sync and a
drift repair would each report a "lag" that says nothing about scheduling latency,
and would quietly poison the metric; `tests/test_observability.py` asserts each of
those is excluded.

Supporting series: `oncall_sync_runs_total{status,trigger}`,
`oncall_group_writes_total{reason}` (handoff vs drift repair),
`oncall_provider_api_errors_total{provider,code}` — which records Slack's
`ok:false` body errors too, since those never reach a status-code counter —
`oncall_rate_limit_hits_total{provider}`, `oncall_unmapped_identities_total`,
and the `oncall_rules{status}` / `oncall_connections{kind,status}` gauges.

### Security

`tests/test_security.py` encodes the review as assertions: no endpoint returns a
stored credential, invite tokens are never retrievable after issue, session
cookies are httpOnly while the CSRF half is deliberately readable, login is
throttled, a wrong password is indistinguishable from an unknown address, and the
OAuth callback only ever redirects to the configured SPA origin. Responses carry
`nosniff`, `DENY` and a `default-src 'none'` CSP; logs pass through a redaction
processor so a stray dict of credentials renders as `[redacted]`.

### Scale

`tests/test_load.py` (run with `-m slow`) seeds ~1,000 rules across 20 orgs and
checks the scheduler's claim stays bounded and index-servable, and that
successive ticks drain the backlog without ever handing the same rule out twice.

## Documentation

| Doc | For |
|---|---|
| [`docs/SETUP.md`](docs/SETUP.md) | Installing, registering the provider apps, first rule |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Deployment, monitoring, alerts, runbook |
| [`docs/PLAN.md`](docs/PLAN.md) | Original design and milestone plan |

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

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE.md). In
short: you can self-host, modify and redistribute this freely, but if you run
a modified version as a network service, you must make the Corresponding
Source available to its users.
