import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/page";
import { Alert } from "@/components/ui/alert";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { ActivityRun } from "@/lib/types";
import { errorMessage } from "./Login";

const FILTERS = [
  { value: "", label: "All" },
  { value: "success", label: "Success" },
  { value: "degraded", label: "Degraded" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
];

const RUN_VARIANT: Record<string, BadgeProps["variant"]> = {
  success: "success",
  degraded: "warning",
  failed: "destructive",
  skipped: "secondary",
};

export default function Activity() {
  const [status, setStatus] = useState("");

  const runs = useQuery({
    queryKey: ["activity", status],
    queryFn: () =>
      api.get<ActivityRun[]>(`/activity${status ? `?status=${status}` : ""}`),
    refetchInterval: 15_000,
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Activity" description="Every sync run, across every rule." />

      <div className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-muted/40 p-1">
        {FILTERS.map((filter) => (
          <button
            key={filter.value}
            onClick={() => setStatus(filter.value)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              status === filter.value
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="pt-6">
          {runs.error && <Alert>{errorMessage(runs.error)}</Alert>}
          {runs.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {status ? `No ${status} runs.` : "Nothing has run yet."}
            </p>
          )}

          <ul className="divide-y divide-border">
            {runs.data?.map((run) => (
              <li key={run.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={RUN_VARIANT[run.status] ?? "secondary"}>{run.status}</Badge>
                  <span className="text-sm font-medium text-foreground">{run.rule_name}</span>
                  <span className="text-xs text-muted-foreground">{run.trigger}</span>
                  <span className="ml-auto text-xs text-muted-foreground/70">
                    {new Date(run.started_at).toLocaleString()}
                    {run.duration_ms !== null && ` · ${run.duration_ms} ms`}
                  </span>
                </div>

                {run.previous_members && run.new_members && (
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {run.previous_members.join(", ") || "—"} → {run.new_members.join(", ")}
                  </p>
                )}
                {run.actions && run.actions.length > 0 && (
                  <p className="mt-1 text-sm text-muted-foreground">{run.actions.join(" · ")}</p>
                )}
                {run.problems && run.problems.length > 0 && (
                  <p className="mt-1 text-sm text-warning">{run.problems.join(" · ")}</p>
                )}
                {run.error && <p className="mt-1 text-sm text-destructive">{run.error}</p>}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
