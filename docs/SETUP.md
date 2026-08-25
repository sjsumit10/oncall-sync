# Setup

Getting On-Call Sync running, connected to PagerDuty and Slack, and verified with
a real handoff.

Three stages: **run the stack**, **register the two provider apps**, then **wire up
your first rule**. Budget about 30 minutes, most of it in the Slack and PagerDuty
consoles.

---

## 1. Prerequisites

| Need | Why |
|---|---|
| Docker + Docker Compose | Runs Postgres, Redis, the API and the worker |
| Node 20+ and npm | The frontend dev server |
| A Slack workspace on **Standard plan or above** | User groups are a paid feature — the whole product depends on them |
| Permission to install Slack apps | Or an admin willing to approve the install |
| A PagerDuty account with at least one schedule | The source of truth for who is on call |
| `ngrok` (or any public tunnel) | Slack and PagerDuty must reach your callbacks |

> **The Slack plan requirement is not negotiable.** On a Free workspace, Slack's
> API rejects every user-group call with `plan_upgrade_required` and nothing in
> this product can work. Check before you spend time on the rest.

---

## 2. Run the stack

```bash
git clone <your-fork> oncall-sync && cd oncall-sync
cp .env.example .env
```

Generate the key that wraps every stored credential, and put it in `.env` as
`CREDENTIAL_KEK`:

```bash
python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

> Losing this key makes every stored provider credential undecryptable and every
> connection has to be re-established. Back it up somewhere other than the
> database — keeping both in one place defeats the point of wrapping the keys.

Start everything:

```bash
make up        # postgres, redis, api, worker
make migrate   # creates the least-privileged app role, then applies migrations
make web       # frontend on http://localhost:5173
```

Check it came up:

```bash
curl -s localhost:8000/health          # {"status":"ok",...}
docker compose logs worker | tail -5   # "worker.started" then cron:tick
```

If the worker exits complaining it *"cannot bypass row-level security"*, that is
deliberate — see [OPERATIONS.md](OPERATIONS.md#database-roles). It refuses to run
as a scheduler that would silently see no rules.

### Ports already in use

If something already binds 5432, 6379 or 8000, override the published ports in
`.env` — container-to-container traffic is unaffected:

```
POSTGRES_PORT=55432
REDIS_PORT=56379
API_PORT=8000
```

---

## 3. Expose the API publicly

Slack's events endpoint and both OAuth callbacks need a public HTTPS URL.

```bash
ngrok http 8000
```

Take the `https://` forwarding address and set it in `.env`, then restart:

```
APP_BASE_URL=https://<your-subdomain>.ngrok-free.app
WEB_BASE_URL=http://localhost:5173
```

```bash
docker compose up -d --force-recreate api worker
```

Everything below derives from `APP_BASE_URL`:

| Purpose | URL |
|---|---|
| Slack OAuth redirect | `$APP_BASE_URL/api/v1/chat/slack/callback` |
| Slack events | `$APP_BASE_URL/api/v1/webhooks/slack/events` |
| PagerDuty OAuth redirect | `$APP_BASE_URL/api/v1/oncall/connections/pagerduty/oauth/callback` |

> ngrok gives you a new subdomain each restart on the free tier, and every URL
> above changes with it. Expect to update both consoles if you restart the tunnel.

---

## 4. Slack app

This is **one app registration, installed by many workspaces** — not one app per
customer. Every org that signs up hits the same `SLACK_CLIENT_ID` and goes through
the same OAuth "Add to Slack" flow from its own Connections page; the callback
(`/api/v1/chat/slack/callback`) resolves which org the install belongs to from the
state token minted when that org clicked *Add to Slack*, not from anything
Slack-specific. You register the app once, in your own Slack account.

> **You do not need to submit this to the Slack App Directory.** The Directory is
> only for organic discovery — being found by search *inside* Slack — and requires
> Slack's own app-review process. A workspace admin can install your app the
> moment it exists, from your own "Add to Slack" link, with zero review from
> Slack. Skip the Directory unless you specifically want that discovery channel.

### Create it from a manifest

Go to <https://api.slack.com/apps> → **Create New App** → **From an app manifest**,
pick your workspace, and paste this — replacing `YOUR-DOMAIN` with your
`APP_BASE_URL` host:

```yaml
display_information:
  name: On-Call Sync
  description: Keeps a group handle pointed at whoever is actually on call
  background_color: "#1f2937"
features:
  bot_user:
    display_name: On-Call Sync
    always_online: true
oauth_config:
  redirect_urls:
    - https://YOUR-DOMAIN/api/v1/chat/slack/callback
  scopes:
    bot:
      - usergroups:read
      - usergroups:write
      - channels:read
      - groups:read
      - chat:write
      - users:read
      - users:read.email
      - team:read
    user:
      - usergroups:write
settings:
  event_subscriptions:
    request_url: https://YOUR-DOMAIN/api/v1/webhooks/slack/events
    bot_events:
      - app_uninstalled
      - tokens_revoked
      - subteam_updated
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

Slack verifies the events URL the moment you submit, so **the stack and the tunnel
must already be running**. The API answers Slack's `url_verification` challenge
automatically.

### Why each scope

| Scope | Used for |
|---|---|
| `usergroups:read` / `usergroups:write` | Reading and rewriting the handle's membership — the core of the product |
| `users:read.email` | Matching PagerDuty people to Slack accounts by email |
| `chat:write` | Posting the handoff message |
| `channels:read`, `groups:read` | Listing channels in the rule builder |
| `team:read`, `users:read` | Naming the workspace and its people in the UI |

**The `user` scope matters more than it looks.** `usergroups.users.update` accepts
both bot and user tokens, but whether a *bot* token is permitted depends on a
workspace setting — if User Groups management is restricted to admins, the bot is
refused no matter its scopes. Approving the user grant at install stores the
installer's token as a fallback. Skip it and the app still installs, but the
Connections page will warn you that there is no fallback if that setting is ever
tightened.

### Copy the credentials

From **Basic Information**, put these in `.env` and restart the API:

```
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_SIGNING_SECRET=...
```

```bash
docker compose up -d --force-recreate api worker
```

The signing secret is what authenticates every inbound Slack event. Without it,
the events endpoint rejects everything with `401` — which is the correct
behaviour, not a misconfiguration to work around.

### Prepare the workspace

Two things the product cannot do for you:

1. **Create the user group.** In Slack: **People & user groups** → **User groups**
   → **Create**. Give it the handle you want people to type, e.g.
   `@devops-on-call`. Membership does not matter — it is about to be managed.
2. **Invite the bot to the announcement channel.** In the channel, run
   `/invite @On-Call Sync`. Slack silently drops messages to channels an app has
   not joined, so the rule builder refuses a channel the bot is not in rather
   than letting you find out at the first handoff.

---

## 5. PagerDuty

Two ways in. OAuth is scoped and revocable and is what you want in production;
the API key is faster if you are just evaluating.

### Option A — OAuth (recommended)

In PagerDuty: **Integrations** → **Developer Tools** → **App Registration** →
**+ New App**.

1. Name it, then under **Functionality** select **OAuth 2.0**.
2. Choose **Scoped OAuth**.
3. **+ Add redirect URL**:
   `https://YOUR-DOMAIN/api/v1/oncall/connections/pagerduty/oauth/callback`
4. Grant **Read** on: **Schedules**, **On-Calls**, **Users** — which is to say
   the scopes `schedules.read`, `oncalls.read` and `users.read`. Nothing else:
   this product never writes to PagerDuty.
5. **Register App**. Copy the Client ID and Secret from the dialog; the secret is
   shown once.

```
PAGERDUTY_CLIENT_ID=...
PAGERDUTY_CLIENT_SECRET=...
```

```bash
docker compose up -d --force-recreate api worker
```

The Connections page only offers the OAuth button when these are set, so if you
skip this step you will only see the API-key form. That is by design, not a bug.

### Option B — read-only API key

**Integrations** → **Developer Tools** → **API Access Keys** → **+ Create New API
Key**. Tick **Read-only** and copy the key.

Nothing goes in `.env` — you paste the key into the app itself, which verifies it
against PagerDuty *before* storing it, so a key that never worked is never saved.

> An account-level API key is unscoped and does not expire. Prefer OAuth wherever
> your org's policies allow it.

---

## 6. Your first rule

With the stack up and both apps registered, open <http://localhost:5173>.

1. **Sign up.** The first account creates the organization and becomes its owner.
2. **Connections → Connect PagerDuty.** Either press the OAuth button or paste
   the read-only key. Expand **Schedules** to confirm your rotations appear.
3. **Connections → Add to Slack.** Approve **both** the app permissions and the
   user permissions.
4. **Rules → New rule.**
   - **Schedule** — your PagerDuty rotation.
   - **Escalation levels** — leave at 1. That is the person actually holding the
     pager; adding levels includes everyone across them.
   - **User group** — the handle you created, e.g. `@devops-on-call`.
   - **Channel** — where handoffs are announced. Only channels the bot has joined
     are listed. Untick *Announce handoffs* for quiet mode.
   - **Fallback member** — a Slack user ID. Worth setting: Slack refuses to leave
     a user group empty, so without one a rule that resolves to nobody leaves the
     handle untouched instead.
5. **Preview** on the rule. This is a dry run — it queries PagerDuty and Slack,
   shows who *would* be set and exactly what would change, and **writes nothing**.
   It runs the same evaluation the scheduler does, so what it shows is what will
   happen.
6. **Sync now** when the preview looks right.

Check Slack: the user group's membership should now be whoever is on call, and
the channel should have a handoff message.

### Fix any unmatched people

People are matched by email. Anyone whose PagerDuty and Slack addresses differ —
contractors, aliases, SSO variance — shows up under **Identities**. Link them by
hand; a manual link always wins over an automatic match and is never overwritten.

Leave them unlinked and they will be **silently skipped at handoff**, which is
exactly the failure this product exists to prevent.

---

## 7. Verify a real handoff

Pressing *Sync now* proves the plumbing. It does not prove the scheduler wakes at
the right moment, which is the actual product.

The quickest honest test is a PagerDuty **override**:

1. In PagerDuty, open the schedule and add an override for a *different* person
   starting a couple of minutes from now.
2. Watch the worker:
   ```bash
   docker compose logs -f worker
   ```
   You should see a `beat.claimed` line at the override boundary, then
   `reconcile.done ... people_changed=True announced=True`.
3. In Slack, the group membership flips to the override person and one handoff
   message is posted.

The rule wakes at the boundary rather than polling, because the on-call window
fetch already told it when the next shift change is. The 5-minute reconcile is
only a safety net.

**Then test the repair path.** Hand-edit the user group in Slack, adding someone
who is not on call. Within five minutes it is corrected — and **no message is
posted**, because repairing drift is not a handoff.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Slack rejects the manifest's events URL | Stack or tunnel not running | Start both, then resubmit |
| Events endpoint returns `401` | `SLACK_SIGNING_SECRET` missing or stale | Copy it from Basic Information, restart the API |
| No **Connect with PagerDuty** button | No OAuth app configured | Set `PAGERDUTY_CLIENT_ID`/`_SECRET`, or use the API key |
| `error=invalid_state` after an OAuth redirect | State expired (10 min) or a different browser finished the flow | Start the connection again in the same browser |
| `error=session_mismatch` | The callback landed in a browser without the session that began it | Sign in and retry in one browser |
| Group list is empty or errors with *Standard plan* | Free Slack workspace | User groups need Standard or above |
| Channel missing from the picker | Bot not in it | `/invite @On-Call Sync`, then **Refresh** |
| Rule stuck on **Not synced yet** | Worker down, or nothing has claimed it | `docker compose logs worker`; check for `cron:tick` |
| Rule **Degraded** | Press *Preview* — it names the reason | Usually an unmapped person or an empty schedule |
| *This workspace restricts who may manage user groups* | Slack workspace setting, and no user token to fall back on | Allow everyone to manage user groups, or reinstall approving the user permissions |
| Connection says **Reconnect required** | Credential revoked upstream | Reconnect on the Connections page; the connection id is preserved so rules keep working |

For alerting, metrics and the on-call runbook, see [OPERATIONS.md](OPERATIONS.md).
