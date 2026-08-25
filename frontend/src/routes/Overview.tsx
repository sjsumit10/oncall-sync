import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Plug,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { EmptyState, PageHeader } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/utils";
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
    <div className="space-y-8">
      <PageHeader title={`Welcome, ${session?.user.name.split(" ")[0] ?? ""}`} />

      {data && data.rules_total === 0 ? (
        <EmptyState
          icon={Plug}
          title="Next: connect your tools"
          description="Connect PagerDuty and install the Slack app, then map a schedule to a user group so mentioning it always reaches whoever is on call."
          action={
            <Button asChild size="sm" className="mt-1">
              <Link to="/connections">
                Go to connections
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          }
        />
      ) : (
        <>
          {needsAttention && (
            <Card className="border-warning/30 bg-warning/5">
              <CardContent className="flex gap-3 pt-6">
                <AlertTriangle className="mt-0.5 size-4.5 shrink-0 text-warning" />
                <div className="space-y-1.5">
                  <p className="text-sm font-medium text-foreground">Needs attention</p>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    {degraded > 0 && (
                      <li>
                        {degraded} rule{degraded > 1 ? "s are" : " is"} not tracking on-call.{" "}
                        <Link
                          to="/rules"
                          className="font-medium text-primary underline-offset-4 hover:underline"
                        >
                          Review rules
                        </Link>
                      </li>
                    )}
                    {(data?.connections_needing_attention ?? 0) > 0 && (
                      <li>
                        {data?.connections_needing_attention} connection
                        {(data?.connections_needing_attention ?? 0) > 1 ? "s need" : " needs"}{" "}
                        reconnecting.{" "}
                        <Link
                          to="/connections"
                          className="font-medium text-primary underline-offset-4 hover:underline"
                        >
                          Fix connections
                        </Link>
                      </li>
                    )}
                  </ul>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <Stat icon={Workflow} label="Rules" value={String(data?.rules_total ?? "—")} />
            <Stat
              icon={CheckCircle2}
              label="Healthy"
              value={String(data?.rules_by_status.healthy ?? 0)}
              tone={degraded > 0 ? "warn" : "ok"}
            />
            <Stat
              icon={Clock}
              label="Last handoff"
              value={
                data?.last_handoff_at
                  ? new Date(data.last_handoff_at).toLocaleString()
                  : "None yet"
              }
            />
          </div>

          <Card>
            <CardContent className="flex items-center justify-between pt-6">
              <p className="text-sm text-muted-foreground">
                See who was notified and what changed at every handoff.
              </p>
              <Link
                to="/activity"
                className="flex items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                Full activity log
                <ArrowRight className="size-3.5" />
              </Link>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  tone?: "ok" | "warn" | "neutral";
}) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between pt-6">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          <p
            className={cn(
              "mt-1.5 text-xl font-semibold tracking-tight",
              tone === "ok" && "text-success",
              tone === "warn" && "text-warning",
              tone === "neutral" && "text-foreground",
            )}
          >
            {value}
          </p>
        </div>
        <div
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-lg",
            tone === "ok" && "bg-success/10 text-success",
            tone === "warn" && "bg-warning/10 text-warning",
            tone === "neutral" && "bg-primary/10 text-primary",
          )}
        >
          <Icon className="size-4.5" />
        </div>
      </CardContent>
    </Card>
  );
}
