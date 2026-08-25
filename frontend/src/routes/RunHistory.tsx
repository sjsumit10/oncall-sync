import { useQuery } from "@tanstack/react-query";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { SyncRun } from "@/lib/types";

const RUN_VARIANT: Record<string, BadgeProps["variant"]> = {
  success: "success",
  degraded: "warning",
  failed: "destructive",
  skipped: "secondary",
};

export function RunHistory({ ruleId }: { ruleId: string }) {
  const runs = useQuery({
    queryKey: ["runs", ruleId],
    queryFn: () => api.get<SyncRun[]>(`/rules/${ruleId}/runs`),
  });

  return (
    <div className="mt-4 border-t border-border pt-4">
      <p className="mb-2 text-sm font-medium text-foreground">Recent runs</p>
      {runs.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {runs.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">Nothing yet — this rule has not run.</p>
      )}
      <ul className="divide-y divide-border">
        {runs.data?.map((run) => (
          <li key={run.id} className="py-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={RUN_VARIANT[run.status] ?? "secondary"}>{run.status}</Badge>
              <span className="text-xs text-muted-foreground">{run.trigger}</span>
              <span className="text-xs text-muted-foreground">
                {new Date(run.started_at).toLocaleString()}
              </span>
              {run.duration_ms !== null && (
                <span className="text-xs text-muted-foreground/70">{run.duration_ms} ms</span>
              )}
            </div>
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
    </div>
  );
}
