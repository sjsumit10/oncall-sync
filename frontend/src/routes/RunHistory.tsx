import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { SyncRun } from "@/lib/types";

const RUN_STYLE: Record<string, string> = {
  success: "bg-emerald-50 text-emerald-700",
  degraded: "bg-amber-50 text-amber-800",
  failed: "bg-red-50 text-red-700",
  skipped: "bg-slate-100 text-slate-600",
};

export function RunHistory({ ruleId }: { ruleId: string }) {
  const runs = useQuery({
    queryKey: ["runs", ruleId],
    queryFn: () => api.get<SyncRun[]>(`/rules/${ruleId}/runs`),
  });

  return (
    <div className="mt-4 border-t border-slate-100 pt-4">
      <p className="mb-2 text-sm font-medium text-slate-700">Recent runs</p>
      {runs.isPending && <p className="text-sm text-slate-500">Loading…</p>}
      {runs.data?.length === 0 && (
        <p className="text-sm text-slate-500">Nothing yet — this rule has not run.</p>
      )}
      <ul className="divide-y divide-slate-100">
        {runs.data?.map((run) => (
          <li key={run.id} className="py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                  RUN_STYLE[run.status] ?? "bg-slate-100 text-slate-600"
                }`}
              >
                {run.status}
              </span>
              <span className="text-xs text-slate-500">{run.trigger}</span>
              <span className="text-xs text-slate-500">
                {new Date(run.started_at).toLocaleString()}
              </span>
              {run.duration_ms !== null && (
                <span className="text-xs text-slate-400">{run.duration_ms} ms</span>
              )}
            </div>
            {run.actions && run.actions.length > 0 && (
              <p className="mt-1 text-sm text-slate-600">{run.actions.join(" · ")}</p>
            )}
            {run.problems && run.problems.length > 0 && (
              <p className="mt-1 text-sm text-amber-800">{run.problems.join(" · ")}</p>
            )}
            {run.error && <p className="mt-1 text-sm text-red-600">{run.error}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
