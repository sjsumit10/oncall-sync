# On-Call Sync — Platform Plan (PagerDuty → Slack)

## Context

When someone pages `@devops-on-call` in Slack, the people notified are whoever happens to be in that Slack user group — a list humans maintain by hand. It goes stale within a rotation or two, so pages reach people who are asleep or off-shift, and miss the person actually holding the pager.

This platform closes that gap: a user signs up, connects their PagerDuty account, installs a Slack app into their workspace, then maps *PagerDuty schedule → Slack user group*. Whenever the on-call person changes per the schedule, we rewrite the user group's membership so the handle resolves to the real on-call person, and post a handoff message to a channel the user picks.

The repo is empty — this is a greenfield build.

**Design constraint that shapes everything:** PagerDuty and Slack are the first integrations, not the only ones. Opsgenie/Grafana OnCall and Microsoft Teams come later. So all provider-specific code sits behind two interfaces (`OncallProvider`, `ChatProvider`) and a registry; nothing outside `app/providers/` may import a vendor SDK or mention "pagerduty"/"slack" in business logic. Teams' analog to a Slack user group is a **Teams tag** (Microsoft Graph `teamwork tags` API), which maps cleanly onto `set_group_members` — the interface is designed with that second implementation in mind, but Teams is explicitly **out of scope** for this build.

### Decisions locked with the user

| Decision | Choice |
|---|---|
| Stack | Python + FastAPI backend, React + Vite frontend |
| PagerDuty auth | OAuth 2.0 primary, read-only REST API key as fallback |
| Tenancy | Multi-tenant SaaS from day one (`org_id` on every row) |
| Change detection | Precise scheduling (enqueue at exact handoff time) + 5-min safety reconcile |
| Handoff message | Per-rule configurable template, with a quiet mode |

---

## Architecture

```
┌──────────────┐   REST/JSON    ┌────────────────────────────┐
│ React + Vite │ ─────────────► │ FastAPI (api)              │
│ (SPA)        │ ◄───────────── │  auth · connections · rules│
└──────────────┘   cookie sess  └─────────┬──────────────────┘
                                          │ shares models + providers
        Slack OAuth / Events ────────────►│
                                ┌─────────▼──────────────────┐
                                │ Postgres                   │
                                │  rules.next_run_at = clock │
                                └─────────┬──────────────────┘
                                          │ claim due rules (SKIP LOCKED)
                                ┌─────────▼──────────────────┐
                                │ ARQ worker (sync engine)   │
                                │  beat 30s → enqueue        │
                                │  reconcile(rule)           │
                                └────┬──────────────┬────────┘
                                     ▼              ▼
                              PagerDuty API     Slack Web API
```

**Postgres is the scheduler, Redis is only the queue.** Each rule carries `next_run_at`; a 30-second beat task claims due rules with `SELECT ... FOR UPDATE SKIP LOCKED` and enqueues them. Delayed jobs never live only in Redis, so a Redis flush costs at most one beat tick rather than silently dropping every future handoff.

### Provider abstraction

`app/domain/interfaces.py` — the only contract business logic knows about:

```python
class OncallProvider(Protocol):
    kind: str                      # "pagerduty"
    auth_modes: tuple[AuthMode, ...]

    async def verify(self, conn: Credentials) -> ProviderHealth: ...
    async def list_schedules(self, conn) -> list[ScheduleRef]: ...
    async def get_oncall_window(self, conn, schedule_id: str,
                                since: datetime, until: datetime) -> list[OncallSpan]: ...
    async def list_users(self, conn) -> list[ProviderUser]: ...

class ChatProvider(Protocol):
    kind: str                      # "slack"

    def install_url(self, state: str) -> str: ...
    async def complete_install(self, code: str) -> ChatInstall: ...
    async def list_groups(self, conn) -> list[GroupRef]: ...      # Slack usergroups / Teams tags
    async def list_channels(self, conn) -> list[ChannelRef]: ...
    async def get_group_members(self, conn, group_id: str) -> list[str]: ...
    async def set_group_members(self, conn, group_id: str, member_ids: list[str]) -> None: ...
    async def find_user_by_email(self, conn, email: str) -> ChatUser | None: ...
    async def post_message(self, conn, channel_id: str, blocks: list, fallback: str) -> MessageRef: ...
```

`OncallSpan` is the key normalization: `(user: ProviderUser, start: datetime, end: datetime | None, level: int)`. Everything the sync engine needs — who is on call now, when the next change happens, which escalation level — derives from one window fetch. A provider that lacks escalation levels returns `level=1`.

Registry in `app/domain/registry.py`: `ONCALL_PROVIDERS: dict[str, OncallProvider]`, `CHAT_PROVIDERS: dict[str, ChatProvider]`. Adding Opsgenie later = one new package + one registry line + one enum value; the sync engine is untouched.

### Repo layout

```
oncall-sync/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, routers, middleware
│   │   ├── config.py               # pydantic-settings
│   │   ├── api/v1/                 # auth, connections, schedules, chat, rules,
│   │   │                           #   identities, runs, webhooks
│   │   ├── core/                   # security, crypto, deps, ratelimit, errors
│   │   ├── db/models/              # SQLAlchemy 2.0 ORM
│   │   ├── domain/                 # interfaces.py, registry.py, types.py
│   │   ├── providers/
│   │   │   ├── oncall/base.py
│   │   │   ├── oncall/pagerduty/   # client.py, oauth.py, provider.py
│   │   │   ├── chat/base.py
│   │   │   └── chat/slack/         # client.py, oauth.py, events.py,
│   │   │                           #   blocks.py, provider.py
│   │   ├── services/               # sync_engine.py, identity_resolver.py,
│   │   │                           #   templating.py, connections.py
│   │   └── worker/                 # arq_app.py, tasks.py, beat.py
│   ├── alembic/
│   └── tests/
├── frontend/                       # Vite + React + TS
├── docker-compose.yml              # postgres, redis, api, worker
└── Makefile
```

---

## Data model

Postgres + SQLAlchemy 2.0 + Alembic. Every tenant-owned table carries `org_id`; a FastAPI dependency injects the caller's org and the repository layer scopes every query. Postgres RLS as a second belt on the tenant tables.

| Table | Purpose | Notable columns |
|---|---|---|
| `organizations` | Tenant root | `name`, `slug` |
| `users` | Members | `org_id`, `email`, `password_hash`, `role` (owner/admin/member) |
| `sessions` | Server-side sessions | Redis-backed; httpOnly cookie |
| `oncall_connections` | A connected PagerDuty account | `org_id`, `kind`, `auth_mode` (oauth\|api_key), `credentials_enc`, `external_account_id`, `subdomain`, `status`, `last_verified_at` |
| `chat_connections` | An installed Slack workspace | `org_id`, `kind`, `external_team_id`, `team_name`, `bot_token_enc`, `user_token_enc`, `scopes`, `installed_by_user_id`, `status` |
| `oncall_schedules` | Cached schedule list | `connection_id`, `external_id`, `name`, `timezone` · unique(conn, external_id) |
| `chat_groups` | Cached user groups | `chat_connection_id`, `external_id`, `handle`, `name`, `is_active` |
| `chat_channels` | Cached channels | `chat_connection_id`, `external_id`, `name`, `is_private`, `bot_is_member` |
| **`sync_rules`** | **The core mapping** | see below |
| `identity_links` | PD user ↔ Slack user | `org_id`, `oncall_connection_id`, `provider_user_id`, `provider_email`, `chat_connection_id`, `chat_user_id`, `source` (auto_email\|manual) |
| `sync_runs` | Execution log | `rule_id`, `trigger`, `status`, `previous_members`, `new_members`, `actions` (jsonb), `error`, timings |
| `audit_logs` | Who changed what | `org_id`, `actor_user_id`, `action`, `target`, `payload` |

`sync_rules` columns:

```
id, org_id, name, enabled
oncall_connection_id, schedule_external_id
chat_connection_id, group_external_id
notify_channel_external_id  (nullable)
escalation_levels  int[]     -- default {1}; union across levels if multiple
message_template   text      -- Jinja sandbox; null = default template
notify_on_change   bool      -- false = quiet mode (update handle, no post)
fallback_chat_user_id text   -- used when nobody resolves (Slack forbids empty groups)
current_members    jsonb     -- last synced chat user ids + PD user snapshot
state_hash         text
next_run_at        timestamptz  -- the scheduler clock
last_synced_at, last_error, consecutive_failures
```

Credentials are envelope-encrypted: a per-org DEK (AES-256-GCM via `cryptography`) wrapped by a KEK from env/KMS, stored as `bytea`. Tokens are never logged; a `SecretStr`-based repr guard covers accidental interpolation.

---

## The sync engine

`app/services/sync_engine.py` — one function, provider-agnostic, the heart of the product.

```
reconcile(rule, trigger):
  1. pg_advisory_xact_lock(rule.id)                # no concurrent runs on one rule
  2. spans = oncall.get_oncall_window(sched, now-1m, now+14d)
  3. current = [s.user for s in spans if s.covers(now) and s.level in rule.escalation_levels]
  4. desired = [resolve_identity(u) for u in current]   # drops unmapped, records them
  5. if not desired:
         use rule.fallback_chat_user if set
         else → mark rule DEGRADED, alert channel, DO NOT touch the group, exit
  6. actual = chat.get_group_members(rule.group_external_id)
  7. if set(actual) != set(desired):  chat.set_group_members(...)      # drift or handoff
  8. if set(rule.current_members) != set(desired) and rule.notify_on_change:
         chat.post_message(rule.notify_channel, render(rule.message_template, ctx))
  9. persist current_members, sync_run, clear/raise consecutive_failures
 10. next_change = min(span boundary > now) from step 2
     rule.next_run_at = min(next_change + jitter(0-30s), now + RECONCILE_INTERVAL)
```

Two details that matter:

- **Steps 7 and 8 are deliberately separate.** Step 7 fires when Slack's actual membership differs from what it should be — including when someone hand-edited the group. Step 8 fires only when the *on-call person actually changed*. Correcting drift must not spam the channel with a phantom handoff.
- **Step 10 is why handoffs are instant.** The window fetch in step 2 already tells us exactly when the next shift boundary is, so we schedule a run for that moment instead of polling blindly. The `min(..., now + 5min)` cap is the safety net that catches retroactive overrides, schedule edits, and manual Slack drift.

`identity_resolver.py`: check `identity_links` → else `find_user_by_email(pd_user.email)` → cache the link with `source=auto_email`. Unresolved PD users surface in the UI for manual linking. Email is the only reliable join key; manual override always wins.

**Reliability.** Per-rule advisory lock; idempotent writes (re-running produces no change); retries with jittered exponential backoff honoring `Retry-After`; `consecutive_failures` opens a circuit and flags the rule in the UI after N failures. Redis token buckets per workspace for Slack (`usergroups.users.update` is Tier 2, ~20/min) and per connection for PagerDuty (~960/min account-wide).

---

## API surface (FastAPI, `/api/v1`)

```
POST   /auth/signup · /auth/login · /auth/logout · GET /auth/me
POST   /orgs/invites                        # teammate invites

GET    /oncall/providers                    # registry-driven; UI renders from this
POST   /oncall/connections/pagerduty/oauth/start
GET    /oncall/connections/pagerduty/oauth/callback
POST   /oncall/connections                  # api_key fallback
GET    /oncall/connections · DELETE /{id}
GET    /oncall/connections/{id}/schedules?refresh=true

GET    /chat/providers
GET    /chat/slack/install                  # → Slack OAuth redirect
GET    /chat/slack/callback
GET    /chat/connections/{id}/groups · /channels
POST   /chat/connections/{id}/groups/refresh

GET    /rules · POST /rules · GET/PATCH/DELETE /rules/{id}
POST   /rules/{id}/sync                     # manual "Sync now"
POST   /rules/{id}/preview                  # dry-run: who would be set, rendered message
GET    /rules/{id}/runs

GET    /identities/unmapped · POST /identities/link

POST   /webhooks/slack/events               # app_uninstalled, tokens_revoked, subteam_updated
```

`subteam_updated` from Slack is a free drift signal — someone hand-edited a managed group, so we enqueue an immediate reconcile rather than waiting for the 5-minute sweep.

---

## Frontend (React + Vite + TS)

TanStack Query, React Router, Tailwind + shadcn/ui, react-hook-form + zod. API client generated from FastAPI's OpenAPI schema (`openapi-typescript` + `openapi-fetch`) so backend contract changes surface as type errors.

| Route | Contents |
|---|---|
| `/signup`, `/login` | Auth |
| `/onboarding` | 3-step wizard: connect PagerDuty → install Slack → create first rule |
| `/connections` | PD + Slack cards: status, scopes, last verified, reconnect, disconnect |
| `/rules` | Table: handle, schedule, **who's on call right now**, status badge, last sync |
| `/rules/new`, `/rules/:id` | Searchable schedule picker, user-group picker, channel picker, escalation-level selector, template editor with live preview, Preview + Sync now |
| `/identities` | Unmapped PagerDuty users → Slack user picker |
| `/activity` | Sync run log with diffs and errors |
| `/settings` | Members, invites, roles |

Default message template (Block Kit):

> :pager: *On-call handoff — {{ schedule_name }}*
> {{ oncall_mention }} is now on call for `@{{ handle }}` (until {{ shift_end }}).
> Thanks {{ previous_name }}! :wave:

Rendered through a Jinja2 `SandboxedEnvironment` with a fixed variable allowlist (`oncall_mention`, `oncall_name`, `previous_name`, `schedule_name`, `handle`, `shift_end`, `shift_start`).

---

## Security

- **Credentials**: envelope encryption (per-org DEK wrapped by env/KMS KEK), never logged, never returned by any API.
- **Slack requests**: verify `X-Slack-Signature` (HMAC-SHA256, signing secret) with a 5-minute replay window before parsing any event body.
- **OAuth**: signed, short-TTL `state` bound to the session and org; exact redirect-URI matching; PKCE where supported.
- **Sessions**: server-side, Redis-backed, httpOnly + SameSite cookies; CSRF token on mutations.
- **Tenancy**: org scoping in the repository layer + Postgres RLS; every fixture-based test asserts cross-org reads return 404.
- **RBAC**: owner/admin may manage connections and rules; member is read-only.
- **Revocation**: handle `app_uninstalled` / `tokens_revoked` by marking the connection `revoked`, pausing its rules, and surfacing a reconnect prompt — never silently retrying dead tokens.

---

## Observability

structlog JSON logs with `org_id`/`rule_id`/`run_id` correlation; Sentry; Prometheus at `/metrics`:

- `sync_runs_total{status, trigger}`
- `handoff_lag_seconds` — histogram of *actual handoff time → group updated*. This is the product's core SLI.
- `provider_api_errors_total{provider, code}`, `rate_limit_hits_total{provider}`
- `unmapped_identities`, `rules_degraded`

---

## Known risks — verify these early

1. **`usergroups.users.update` token type.** Slack has historically restricted user-group writes to *user* tokens. **Spike this on day one of M3**: try a bot token with `usergroups:write`; if rejected, request the user scope during install and store the installing user's token — which means handling that user leaving the workspace (detect, then prompt an admin to re-auth). This is the single highest-impact unknown in the plan and it decides part of the install flow.
2. **Slack user groups are a paid-plan feature (Pro and above).** Free workspaces cannot use the core feature at all. Detect the `paid_only` error at install time and say so plainly rather than failing at first sync.
3. **Slack rejects an empty user group.** Hence `fallback_chat_user_id` and the "never clear the group" rule in step 5 — a stale handle beats a handle that pages nobody.
4. **PagerDuty v3 webhooks have no on-call-change event.** Polling is the only reliable source of truth; the precise-scheduling design is what keeps it cheap and fast. Do not plan around a webhook that does not exist.
5. **Email mismatch** between PagerDuty and Slack (aliases, contractors, SSO variance) is the most common real-world failure. The `/identities` manual-link UI is not a nice-to-have.
6. **Slack notifies on mention, not on membership change.** That's precisely why this works — but it means a user group updated *after* someone types the message does not retroactively notify. Correctness of *timing* is the product.

---

## Milestones

| # | Milestone | Contents |
|---|---|---|
| **M0** | Scaffolding | Monorepo, docker-compose (postgres/redis/api/worker), Alembic, config, CI (ruff, mypy, pytest, vitest) |
| **M1** | Auth + tenancy | Orgs, users, sessions, RBAC, invites, org-scoping dependency + RLS, React shell with auth routing |
| **M2** | PagerDuty connection | `OncallProvider` interface + registry, PD client (httpx, retries, rate limits), OAuth flow + API-key fallback, credential encryption, schedule listing + cache |
| **M3** | Slack install | `ChatProvider` interface, OAuth v2 install, **token-type spike (risk 1)**, signature-verified events endpoint, user-group + channel listing, `app_uninstalled`/`tokens_revoked` handling |
| **M4** | Rules + identities | Rule CRUD, identity resolver, `/identities` UI, rule builder UI with pickers, `/preview` dry-run |
| **M5** | Sync engine | `reconcile()`, beat scheduler + ARQ worker, advisory locks, drift correction, `sync_runs`, "Sync now" |
| **M6** | Handoff messages | Block Kit renderer, sandboxed templating, per-rule template editor with live preview, quiet mode |
| **M7** | Reliability + observability | Circuit breaker, backoff, metrics, `handoff_lag_seconds`, activity log UI, degraded-rule alerting |
| **M8** | Hardening | Security review, load test (~1k rules), onboarding polish, docs, **extensibility proof: a stub second provider implemented against the interfaces to confirm no vendor leakage** |

M8's extensibility proof is the checkpoint that the abstraction actually holds — if adding a stub provider requires touching the sync engine, the interface is wrong and it's far cheaper to learn that here than mid-Teams-integration.

---

## Verification

**Unit** — `pytest` + `respx` for mocked PagerDuty/Slack HTTP. The sync engine takes an injectable clock (`freezegun` in tests) and fake providers, so every handoff case is testable without network: handoff, override mid-shift, drift correction (must *not* post), empty on-call → fallback, empty on-call → no fallback (must not clear), unmapped user, multi-level escalation, rate-limit retry, token revoked mid-run.

**Integration** — testcontainers Postgres; real Alembic migrations; cross-org isolation assertions on every endpoint.

**End-to-end (manual, the real proof)**
1. `docker compose up`; `ngrok http 8000` for Slack OAuth + events redirect URIs.
2. PagerDuty developer account: create a schedule with two users on a short rotation (or drive handoffs with overrides).
3. Slack dev workspace on a **paid plan** (risk 2): create `@devops-on-call`, install the app.
4. Sign up → connect PagerDuty → install Slack → create a rule mapping schedule → `@devops-on-call`, notify `#ops`.
5. `POST /rules/{id}/preview` → confirm the resolved person and rendered message before anything is written.
6. `POST /rules/{id}/sync` → confirm group membership in Slack and the message in `#ops`.
7. Create a PagerDuty override to force a handoff → confirm the worker fires **at the boundary** (check `handoff_lag_seconds`), membership updates, one message posts.
8. Hand-edit the Slack group → confirm the next reconcile repairs it and posts **nothing**.
9. Remove the identity link → confirm the rule goes degraded, the group is *not* cleared, and `/identities` shows the unmapped user.
10. Uninstall the Slack app → confirm the connection flips to `revoked` and its rules pause.

**Frontend** — vitest + Testing Library on the rule builder and template preview; Playwright smoke test over the onboarding wizard.
