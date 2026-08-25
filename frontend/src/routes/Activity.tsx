import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Card } from "@/components/ui";
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

const RUN_STYLE: Record<string, string> = {
  success: "bg-emerald-50 text-emerald-700",
  degraded: "bg-amber-50 text-amber-800",
  failed: "bg-red-50 text-red-700",
  skipped: "bg-slate-100 text-slate-600",
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
      <h1 className="text-xl font-semibold text-slate-900">Activity</h1>

      <Card>
        <div className="mb-4 flex flex-wrap gap-2">
          {FILTERS.map((filter) => (
            <button
              key={filter.value}
              onClick={() => setStatus(filter.value)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                status === filter.value
                  ? "bg-slate-900 text-white"
                  : "border border-slate-300 text-slate-700"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>

        {runs.error && <Alert>{errorMessage(runs.error)}</Alert>}
        {runs.data?.length === 0 && (
          <p className="text-sm text-slate-500">
            {status ? `No ${status} runs.` : "Nothing has run yet."}
          </p>
        )}

        <ul className="divide-y divide-slate-100">
          {runs.data?.map((run) => (
            <li key={run.id} className="py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    RUN_STYLE[run.status] ?? "bg-slate-100 text-slate-600"
                  }`}
                >
                  {run.status}
                </span>
                <span className="text-sm font-medium text-slate-900">{run.rule_name}</span>
                <span className="text-xs text-slate-500">{run.trigger}</span>
                <span className="ml-auto text-xs text-slate-400">
                  {new Date(run.started_at).toLocaleString()}
                  {run.duration_ms !== null && ` · ${run.duration_ms} ms`}
                </span>
              </div>

              {run.previous_members && run.new_members && (
                <p className="mt-1 font-mono text-xs text-slate-500">
                  {run.previous_members.join(", ") || "—"} → {run.new_members.join(", ")}
                </p>
              )}
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
      </Card>
    </div>
  );
}
