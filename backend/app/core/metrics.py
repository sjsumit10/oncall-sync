"""Prometheus instrumentation.

The metric that matters is ``oncall_handoff_lag_seconds``: how long after a shift
actually changed did the group handle catch up. Everything else is diagnosis —
that one is the product working or not.
"""

from prometheus_client import Counter, Gauge, Histogram

SYNC_RUNS = Counter(
    "oncall_sync_runs_total",
    "Reconcile runs, by outcome and what triggered them.",
    ["status", "trigger"],
)

#: Seconds between a shift changing at the provider and the handle catching up.
#: Bucketed around the beat interval: a handoff inside one tick is the target,
#: anything past a few minutes means the safety reconcile caught it rather than
#: the predicted wake-up, and past an hour something is broken.
HANDOFF_LAG = Histogram(
    "oncall_handoff_lag_seconds",
    "Delay between an on-call shift changing and the group handle being updated.",
    buckets=(1, 5, 10, 30, 60, 120, 300, 900, 3600, float("inf")),
)

GROUP_WRITES = Counter(
    "oncall_group_writes_total",
    "Writes to a chat group's membership, by why they happened.",
    ["reason"],
)

ANNOUNCEMENTS = Counter(
    "oncall_announcements_total",
    "Messages posted to a channel, by kind.",
    ["kind"],
)

PROVIDER_ERRORS = Counter(
    "oncall_provider_api_errors_total",
    "Provider API calls that failed, by provider and status code.",
    ["provider", "code"],
)

RATE_LIMIT_HITS = Counter(
    "oncall_rate_limit_hits_total",
    "Times we waited on our own rate limiter or were told to back off.",
    ["provider"],
)

IDENTITIES_UNMAPPED = Counter(
    "oncall_unmapped_identities_total",
    "On-call people encountered with no matching chat account.",
)

#: Point-in-time state, refreshed when /metrics is scraped.
RULES = Gauge("oncall_rules", "Sync rules by status.", ["status"])
CONNECTIONS = Gauge(
    "oncall_connections", "Provider connections by kind and status.", ["kind", "status"]
)
