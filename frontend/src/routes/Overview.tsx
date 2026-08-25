import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import type { Overview as OverviewData } from "@/lib/types";

export default function Overview() {
  const { data: session } = useSession();
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => api.get<OverviewData>("/overview"),
    refetchInterval: 30_000,
  });

  const data = overview.data;
  const degraded = (data?.rules_by_status.degraded ?? 0) + (data?.rules_by_status.failing ?? 0);
  const needsAttention = degraded > 0 || (data?.connections_needing_attention ?? 0) > 0;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">
        Welcome, {session?.user.name.split(" ")[0]}
      </h1>

      {data && data.rules_total === 0 ? (
        <Card title="Next: connect your tools">
          <p className="text-sm text-slate-600">
            Connect PagerDuty and install the Slack app, then map a schedule to a user group so
            mentioning it always reaches whoever is on call.
          </p>
          <Link to="/connections" className="mt-3 inline-block text-sm underline">
            Go to connections
          </Link>
        </Card>
      ) : (
        <>
          {needsAttention && (
            <Card>
              <p className="text-sm font-medium text-amber-800">Needs attention</p>
              <ul className="mt-2 space-y-1 text-sm text-slate-700">
                {degraded > 0 && (
                  <li>
                    {degraded} rule{degraded > 1 ? "s are" : " is"} not tracking on-call.{" "}
                    <Link to="/rules" className="underline">
                      Review rules
                    </Link>
                  </li>
                )}
                {(data?.connections_needing_attention ?? 0) > 0 && (
                  <li>
                    {data?.connections_needing_attention} connection
                    {(data?.connections_needing_attention ?? 0) > 1 ? "s need" : " needs"}{" "}
                    reconnecting.{" "}
                    <Link to="/connections" className="underline">
                      Fix connections
                    </Link>
                  </li>
                )}
              </ul>
            </Card>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Rules" value={String(data?.rules_total ?? "—")} />
            <Stat
              label="Healthy"
              value={String(data?.rules_by_status.healthy ?? 0)}
              tone={degraded > 0 ? "warn" : "ok"}
            />
            <Stat
              label="Last handoff"
              value={
                data?.last_handoff_at
                  ? new Date(data.last_handoff_at).toLocaleString()
                  : "None yet"
              }
            />
          </div>

          <Card>
            <Link to="/activity" className="text-sm underline">
              See the full activity log
            </Link>
          </Card>
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "neutral";
}) {
  const colour =
    tone === "ok" ? "text-emerald-700" : tone === "warn" ? "text-amber-800" : "text-slate-900";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${colour}`}>{value}</p>
    </div>
  );
}
