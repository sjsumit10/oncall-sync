# Operations

Running On-Call Sync in anger: what to configure, what to watch, and what to do
when a handle stops tracking.

## Deployment shape

Four processes, two of them yours to scale:

| Process | Role | Scale |
|---|---|---|
| `api` | HTTP API, OAuth callbacks, Slack events | Horizontally; stateless |
| `worker` | Beat scheduler and the reconcile loop | Horizontally; work is claimed, not partitioned |
| `postgres` | State **and the scheduler's clock** | One primary |
| `redis` | Job queue, sessions, rate-limit counters | One instance |

Multiple workers are safe: each beat tick claims due rules with
`FOR UPDATE SKIP LOCKED` and leases them, and every reconcile takes a per-rule
advisory lock. Two workers cannot process the same rule at once, and a worker that
dies mid-run releases its rules when the lease expires.

## Database roles

Two roles, and the split is load-bearing:

- **`DATABASE_URL`** — the runtime role. Must be neither superuser nor the table
  owner, because both bypass row-level security and would make the tenant
  isolation policies decorative. `make db-bootstrap` creates it.
- **`DATABASE_ADMIN_URL`** — the owner. Runs migrations, and the scheduler's
  cross-tenant claim. **Must be able to bypass RLS**; the worker refuses to start
  otherwise, because a scheduler that silently sees nothing looks perfectly
  healthy while never firing a handoff.

## Required configuration

```
CREDENTIAL_KEK          32 bytes, urlsafe-base64. Wraps every per-org data key.
SESSION_SECRET          Server-side session signing.
COOKIE_SECURE=true      Never false outside local development.
DATABASE_URL            App role (non-owner, non-superuser).
DATABASE_ADMIN_URL      Owner role.
REDIS_URL
APP_BASE_URL            Public URL; OAuth redirect URIs are derived from it.
WEB_BASE_URL            SPA origin; the only place callbacks redirect to.
```

Losing `CREDENTIAL_KEK` means every stored provider credential becomes
undecryptable and every connection has to be re-established. Back it up
separately from the database — holding both in one place defeats the point of
wrapping the keys at all.

### Outbound email (password reset)

```
SMTP_HOST               Empty disables sending — see below.
SMTP_PORT               587 for STARTTLS (most providers), 465 for implicit TLS.
SMTP_USERNAME
SMTP_PASSWORD
SMTP_USE_TLS=false      true only for a port-465, implicit-TLS provider.
SMTP_FROM_EMAIL
SMTP_FROM_NAME=On-Call Sync
```

`POST /api/v1/auth/password-reset/request` always answers the same way
whether or not the address is registered — that is the point, since a
different response would let an attacker enumerate accounts. With
`SMTP_HOST` unset the endpoint still answers normally; it logs
`password_reset.email_not_configured` and sends nothing, so this fails loud
in the logs rather than silently pretending to work. The reset link itself
is only valid for 5 minutes, held in Redis — losing Redis invalidates every
outstanding reset link, which is a fine trade for a bearer credential mailed
in plain text.

## Monitoring

Scrape **two** targets: the API at `/metrics`, and each worker at
`WORKER_METRICS_PORT` (9100). The worker does nearly all the reconciling, so its
counters carry the signal; the API is where the fleet gauges live.

### The SLI

`oncall_handoff_lag_seconds` — seconds between a shift changing at the provider
and the handle catching up. It counts only scheduled runs that moved membership
between two known states, so manual syncs, first syncs and drift repairs cannot
flatter it.

```promql
histogram_quantile(0.95, rate(oncall_handoff_lag_seconds_bucket[1h]))
```

Expect p95 within roughly one beat interval. Sustained values near the 5-minute
reconcile interval mean predicted wake-ups are being missed and the safety net is
doing the work.

### Alerts worth having

| Condition | Meaning |
|---|---|
| `oncall_rules{status="degraded"} > 0` for 15m | A handle has stopped tracking on-call |
| `oncall_rules{status="failing"} > 0` | Circuit open after 5 consecutive failures |
| `oncall_connections{status="needs_reauth"} > 0` | A credential was revoked; nothing will sync |
| `rate(oncall_sync_runs_total{status="failed"}[15m]) > 0` | Provider trouble |
| `absent_over_time(up{job="oncall-worker"}[5m])` | No worker; no handoffs at all |

`oncall_rate_limit_hits_total` rising means the fleet is outgrowing the current
per-tenant budgets rather than anything being broken.

## Runbook

**A rule is degraded.** Open the rule and press *Preview*. It runs the same
evaluation the reconciler does, so it will name the problem. Almost always one of:

- *No chat account matched for X* — their PagerDuty and chat email addresses
  differ. Link them by hand under **Identities**.
- *Nobody is on call* — a genuine gap in the schedule. Set a fallback member on
  the rule so the handle points at someone rather than nobody.
- *This workspace restricts who may manage user groups* — either allow everyone
  to manage user groups in the workspace settings, or reinstall as an admin so
  the installer's token can be used as a fallback.

A degraded rule **never empties the handle**. It stays pointed at whoever it last
contained, because a stale handle still pages a human.

**A connection needs reconnecting.** Its credential was revoked. Reconnect from
**Connections**; the connection id is preserved, so existing rules keep working
without being recreated.

**Handoffs are late.** Check the worker is up and the beat is ticking
(`beat.claimed` log lines). Then check `oncall_rate_limit_hits_total` — if the
provider is throttling, reconciles queue behind the limiter.

**A group was edited by hand.** It self-heals: Slack's `subteam_updated` event
triggers an immediate reconcile, and the periodic reconcile catches it regardless.
No handoff message is posted for a repair.

## Backups

`organizations`, `users`, connections and `sync_rules` are the irreplaceable
state. `sync_runs` is an audit log and can be truncated; consider a retention job
once it grows, as nothing reads rows older than the activity page shows.

Cached tables (`oncall_schedules`, `chat_groups`, `chat_channels`) rebuild from
the providers on demand and need no backup.
