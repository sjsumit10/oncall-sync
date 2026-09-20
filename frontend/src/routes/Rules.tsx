import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, History, Pause, Pencil, Play, Plug, Trash2, Workflow } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/page";
import { Alert } from "@/components/ui/alert";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { useConnections, useGroups, useSchedules } from "@/lib/connections";
import type { RulePreview, SyncRule, SyncRun } from "@/lib/types";
import { errorMessage } from "./Login";
import { RulePreviewPanel } from "./RulePreviewPanel";
import { RunHistory } from "./RunHistory";

const STATUS_LABEL: Record<string, string> = {
  pending: "Not synced yet",
  healthy: "Healthy",
  degraded: "Degraded",
  failing: "Failing",
};

const STATUS_VARIANT: Record<string, BadgeProps["variant"]> = {
  pending: "secondary",
  healthy: "success",
  degraded: "warning",
  failing: "destructive",
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
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Sync rules</h1>
        {canManage && ready && (
          <Button asChild>
            <Link to="/rules/new">New rule</Link>
          </Button>
        )}
      </div>

      {!isPending && !ready && (
        <EmptyState
          icon={Plug}
          title="Connect your tools first"
          description="Connect an on-call provider and install a chat workspace, then come back to build a rule."
          action={
            <Button asChild size="sm" className="mt-1">
              <Link to="/connections">Go to connections</Link>
            </Button>
          }
        />
      )}

      {rules.data?.length === 0 && ready && (
        <EmptyState
          icon={Workflow}
          title="No rules yet"
          description="Map a schedule to a group handle so mentioning it always reaches whoever is on call."
        />
      )}

      <div className="space-y-4">
        {rules.data?.map((rule) => (
          <RuleCard key={rule.id} rule={rule} canManage={canManage} />
        ))}
      </div>
    </div>
  );
}

function RuleCard({ rule, canManage }: { rule: SyncRule; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [showRuns, setShowRuns] = useState(false);

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
  const syncNow = useMutation({
    mutationFn: () => api.post<SyncRun>(`/rules/${rule.id}/sync`),
    onSuccess: () => {
      setPreview(null);
      setShowRuns(true);
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["runs", rule.id] });
    },
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
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>{rule.name}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-center gap-3">
          <code className="text-sm font-medium text-foreground">@{handle}</code>
          <span className="text-sm text-muted-foreground">← {scheduleName}</span>
          <Badge variant={STATUS_VARIANT[rule.status] ?? "secondary"} dot>
            {STATUS_LABEL[rule.status] ?? rule.status}
          </Badge>
          {!rule.enabled && <Badge variant="secondary">Paused</Badge>}
          <div className="ml-auto flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => runPreview.mutate()}
              disabled={runPreview.isPending}
            >
              <Eye className="size-4" />
              {runPreview.isPending ? "Checking…" : "Preview"}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setShowRuns((open) => !open)}>
              <History className="size-4" />
              {showRuns ? "Hide runs" : "Runs"}
            </Button>
            {canManage && (
              <>
                <Button onClick={() => syncNow.mutate()} size="sm" disabled={syncNow.isPending}>
                  {syncNow.isPending ? "Syncing…" : "Sync now"}
                </Button>
                <Button variant="outline" size="sm" asChild>
                  <Link to={`/rules/${rule.id}/edit`}>
                    <Pencil className="size-4" />
                    Edit
                  </Link>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => toggle.mutate()}
                  disabled={toggle.isPending}
                >
                  {rule.enabled ? <Pause className="size-4" /> : <Play className="size-4" />}
                  {rule.enabled ? "Pause" : "Resume"}
                </Button>
                <Button
                  variant="destructive-outline"
                  size="sm"
                  onClick={() => remove.mutate()}
                  disabled={remove.isPending}
                >
                  <Trash2 className="size-4" />
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>

        <p className="mt-2 text-xs text-muted-foreground">
          Escalation level{rule.escalation_levels.length > 1 ? "s" : ""}{" "}
          {rule.escalation_levels.join(", ")}
          {rule.notify_on_change ? " · announces handoffs" : " · quiet mode"}
          {rule.last_synced_at && ` · synced ${new Date(rule.last_synced_at).toLocaleString()}`}
        </p>

        {rule.last_error && (
          <div className="mt-3">
            <Alert>{rule.last_error}</Alert>
          </div>
        )}
        {runPreview.error && (
          <div className="mt-3">
            <Alert>{errorMessage(runPreview.error)}</Alert>
          </div>
        )}
        {syncNow.error && (
          <div className="mt-3">
            <Alert>{errorMessage(syncNow.error)}</Alert>
          </div>
        )}
        {preview && <RulePreviewPanel preview={preview} />}
        {showRuns && <RunHistory ruleId={rule.id} />}
      </CardContent>
    </Card>
  );
}
