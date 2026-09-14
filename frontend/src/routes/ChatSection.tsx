import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, Unplug } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import type {
  AvailableTeam,
  ChatConnection,
  ChatGroup,
  ChatProvider,
  ConnectionHealth,
} from "@/lib/types";
import { errorMessage } from "./Login";
import { StatusBadge } from "./StatusBadge";

//: What to call a connection's "workspace" in prose — Slack calls it a
//: workspace, Teams calls it a tenant.
function workspaceLabel(kind: string): string {
  return kind === "teams" ? "Microsoft Teams tenant" : "Slack workspace";
}

export function ChatSection({ canManage }: { canManage: boolean }) {
  const providers = useQuery({
    queryKey: ["chat-providers"],
    queryFn: () => api.get<ChatProvider[]>("/chat/providers"),
  });
  const connections = useQuery({
    queryKey: ["chat-connections"],
    queryFn: () => api.get<ChatConnection[]>("/chat/connections"),
  });

  return (
    <>
      {connections.data?.map((connection) => (
        <WorkspaceCard key={connection.id} connection={connection} canManage={canManage} />
      ))}
      {providers.data
        ?.filter((provider) => !connections.data?.some((c) => c.kind === provider.kind))
        .map((provider) => (
          <InstallCard key={provider.kind} provider={provider} canManage={canManage} />
        ))}
    </>
  );
}

function WorkspaceCard({
  connection,
  canManage,
}: {
  connection: ChatConnection;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [showGroups, setShowGroups] = useState(false);

  const verify = useMutation({
    mutationFn: () => api.post<ConnectionHealth>(`/chat/connections/${connection.id}/verify`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["chat-connections"] }),
  });
  const disconnect = useMutation({
    mutationFn: () => api.del<void>(`/chat/connections/${connection.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["chat-connections"] }),
  });

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>{connection.team_name}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={connection.status} />
          <span className="text-sm text-muted-foreground">
            {workspaceLabel(connection.kind)} {connection.external_team_id}
            {connection.last_verified_at &&
              ` · verified ${new Date(connection.last_verified_at).toLocaleString()}`}
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowGroups((open) => !open)}>
              {showGroups ? "Hide groups" : "User groups"}
            </Button>
            {canManage && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => verify.mutate()}
                  disabled={verify.isPending}
                >
                  {verify.isPending ? "Checking…" : "Test"}
                </Button>
                <Button
                  variant="destructive-outline"
                  size="sm"
                  onClick={() => disconnect.mutate()}
                  disabled={disconnect.isPending}
                >
                  <Unplug className="size-4" />
                  Disconnect
                </Button>
              </>
            )}
          </div>
        </div>

        {connection.kind === "slack" && !connection.has_user_token && (
          <p className="mt-3 flex items-start gap-2 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            Installed without a user token. If this workspace restricts who may manage user
            groups, updates will fail — reinstall and approve the user permissions to add a
            fallback.
          </p>
        )}
        {connection.last_error && (
          <p className="mt-3 text-sm text-destructive">{connection.last_error}</p>
        )}
        {verify.data && (
          <p className={`mt-3 text-sm ${verify.data.ok ? "text-success" : "text-destructive"}`}>
            {verify.data.detail}
          </p>
        )}
        {connection.kind === "teams" && !connection.external_resource_id ? (
          <SelectTeam connectionId={connection.id} />
        ) : (
          showGroups && <Groups connectionId={connection.id} kind={connection.kind} />
        )}
      </CardContent>
    </Card>
  );
}

function SelectTeam({ connectionId }: { connectionId: string }) {
  const queryClient = useQueryClient();

  const teams = useQuery({
    queryKey: ["available-teams", connectionId],
    queryFn: () => api.get<AvailableTeam[]>(`/chat/connections/${connectionId}/available-teams`),
  });
  const select = useMutation({
    mutationFn: (teamId: string) =>
      api.patch<ChatConnection>(`/chat/connections/${connectionId}/team`, { team_id: teamId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["chat-connections"] }),
  });

  return (
    <div className="mt-4 border-t border-border pt-4">
      <p className="mb-2 text-sm font-medium text-foreground">Select a Team</p>
      <p className="mb-3 text-sm text-muted-foreground">
        A tenant can contain many Teams — pick the one whose on-call tag and channel this
        connection should manage.
      </p>
      {teams.error && <Alert>{errorMessage(teams.error)}</Alert>}
      {select.error && <Alert>{errorMessage(select.error)}</Alert>}
      {teams.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No Teams found for the account that installed this connection.
        </p>
      )}
      {teams.data && teams.data.length > 0 && (
        <Select disabled={select.isPending} onValueChange={(value) => select.mutate(value)}>
          <SelectTrigger className="w-64">
            <SelectValue placeholder="Choose a Team…" />
          </SelectTrigger>
          <SelectContent>
            {teams.data.map((team) => (
              <SelectItem key={team.id} value={team.id}>
                {team.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

function Groups({ connectionId, kind }: { connectionId: string; kind: string }) {
  const queryClient = useQueryClient();
  const key = ["chat-groups", connectionId];

  const groups = useQuery({
    queryKey: key,
    queryFn: () => api.get<ChatGroup[]>(`/chat/connections/${connectionId}/groups`),
  });
  const refresh = useMutation({
    mutationFn: () =>
      api.get<ChatGroup[]>(`/chat/connections/${connectionId}/groups?refresh=true`),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });

  return (
    <div className="mt-4 border-t border-border pt-4">
      <div className="mb-2 flex items-center gap-3">
        <span className="text-sm font-medium text-foreground">
          User groups {groups.data && `(${groups.data.length})`}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
        >
          <RefreshCw className={`size-3.5 ${refresh.isPending ? "animate-spin" : ""}`} />
          {refresh.isPending ? "Refreshing…" : "Refresh"}
        </Button>
      </div>
      {groups.error && <Alert>{errorMessage(groups.error)}</Alert>}
      {refresh.error && <Alert>{errorMessage(refresh.error)}</Alert>}
      {groups.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {kind === "teams"
            ? "No tags yet. Create one in Teams, then refresh."
            : "No user groups yet. Create one in Slack, then refresh."}
        </p>
      )}
      <ul className="divide-y divide-border">
        {groups.data?.map((group) => (
          <li key={group.id} className="flex items-center gap-3 py-2">
            <code className="text-sm text-foreground">@{group.handle}</code>
            <span className="text-sm text-muted-foreground">{group.name}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function InstallCard({
  provider,
  canManage,
}: {
  provider: ChatProvider;
  canManage: boolean;
}) {
  const start = useMutation({
    mutationFn: () => api.post<{ install_url: string }>(`/chat/${provider.kind}/install/start`),
    onSuccess: ({ install_url }) => {
      window.location.href = install_url;
    },
  });

  return (
    <Card className="border-dashed">
      <CardHeader className="pb-4">
        <CardTitle>Install {provider.display_name}</CardTitle>
      </CardHeader>
      <CardContent>
        {!provider.install_configured ? (
          <p className="text-sm text-muted-foreground">
            This deployment has no {provider.display_name} app configured.
          </p>
        ) : !canManage ? (
          <p className="text-sm text-muted-foreground">
            Ask an admin or owner to install {provider.display_name}.
          </p>
        ) : (
          <>
            <Button onClick={() => start.mutate()} disabled={start.isPending}>
              Add to {provider.display_name}
            </Button>
            <p className="mt-3 text-xs text-muted-foreground">
              {provider.kind === "teams"
                ? "One tenant admin approving covers your whole organization — no per-user setup needed."
                : "Approve both the app and the user permissions. The user grant is the fallback " +
                  "for workspaces that restrict who may manage user groups — without it, updates " +
                  "fail there."}
            </p>
            {start.error && (
              <div className="mt-3">
                <Alert>{errorMessage(start.error)}</Alert>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
