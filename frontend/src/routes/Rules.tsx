import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { useConnections, useGroups, useSchedules } from "@/lib/connections";
import type { RulePreview, SyncRule } from "@/lib/types";
import { errorMessage } from "./Login";
import { RulePreviewPanel } from "./RulePreviewPanel";

const STATUS_LABEL: Record<string, string> = {
  pending: "Not synced yet",
  healthy: "Healthy",
  degraded: "Degraded",
  failing: "Failing",
};

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-slate-100 text-slate-600",
  healthy: "bg-emerald-50 text-emerald-700",
  degraded: "bg-amber-50 text-amber-800",
  failing: "bg-red-50 text-red-700",
};

export default function Rules() {
  const { data: session } = useSession();
  const canManage = session?.user.role === "owner" || session?.user.role === "admin";
  const { oncall, chat, isPending } = useConnections();

  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: () => api.get<SyncRule[]>("/rules"),
  });

  const ready = oncall.length > 0 && chat.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center">
        <h1 className="text-xl font-semibold text-slate-900">Sync rules</h1>
        {canManage && ready && (
          <Link className="ml-auto" to="/rules/new">
            <Button>New rule</Button>
          </Link>
        )}
      </div>

      {!isPending && !ready && (
        <Card>
          <p className="text-sm text-slate-600">
            Connect an on-call provider and install a chat workspace first.
          </p>
          <Link to="/connections" className="mt-3 inline-block text-sm underline">
            Go to connections
          </Link>
        </Card>
      )}

      {rules.data?.length === 0 && ready && (
        <Card>
          <p className="text-sm text-slate-600">
            No rules yet. Map a schedule to a group handle so mentioning it always reaches
            whoever is on call.
          </p>
        </Card>
      )}

      {rules.data?.map((rule) => (
        <RuleCard key={rule.id} rule={rule} canManage={canManage} />
      ))}
    </div>
  );
}

function RuleCard({ rule, canManage }: { rule: SyncRule; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<RulePreview | null>(null);

  const schedules = useSchedules(rule.oncall_connection_id);
  const groups = useGroups(rule.chat_connection_id);
  const scheduleName =
    schedules.data?.find((s) => s.external_id === rule.schedule_external_id)?.name ??
    rule.schedule_external_id;
  const handle =
    groups.data?.find((g) => g.external_id === rule.group_external_id)?.handle ??
    rule.group_external_id;

  const runPreview = useMutation({
    mutationFn: () => api.post<RulePreview>(`/rules/${rule.id}/preview`),
    onSuccess: setPreview,
  });
  const toggle = useMutation({
    mutationFn: () => api.patch<SyncRule>(`/rules/${rule.id}`, { enabled: !rule.enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });
  const remove = useMutation({
    mutationFn: () => api.del<void>(`/rules/${rule.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });

  return (
    <Card title={rule.name}>
      <div className="flex flex-wrap items-center gap-3">
        <code className="text-sm text-slate-900">@{handle}</code>
        <span className="text-sm text-slate-500">← {scheduleName}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            STATUS_STYLE[rule.status] ?? "bg-slate-100 text-slate-600"
          }`}
        >
          {STATUS_LABEL[rule.status] ?? rule.status}
        </span>
        {!rule.enabled && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
            Paused
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => runPreview.mutate()} disabled={runPreview.isPending}>
            {runPreview.isPending ? "Checking…" : "Preview"}
          </Button>
          {canManage && (
            <>
              <Button variant="ghost" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
                {rule.enabled ? "Pause" : "Resume"}
              </Button>
              <Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
                Delete
              </Button>
            </>
          )}
        </div>
      </div>

      <p className="mt-2 text-xs text-slate-500">
        Escalation level{rule.escalation_levels.length > 1 ? "s" : ""}{" "}
        {rule.escalation_levels.join(", ")}
        {rule.notify_on_change ? " · announces handoffs" : " · quiet mode"}
        {rule.last_synced_at && ` · synced ${new Date(rule.last_synced_at).toLocaleString()}`}
      </p>

      {rule.last_error && <div className="mt-3"><Alert>{rule.last_error}</Alert></div>}
      {runPreview.error && (
        <div className="mt-3">
          <Alert>{errorMessage(runPreview.error)}</Alert>
        </div>
      )}
      {preview && <RulePreviewPanel preview={preview} />}
    </Card>
  );
}
