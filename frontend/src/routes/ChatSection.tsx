import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import type { ChatConnection, ChatGroup, ChatProvider, ConnectionHealth } from "@/lib/types";
import { errorMessage } from "./Login";
import { StatusBadge } from "./StatusBadge";

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
    <Card title={connection.team_name}>
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={connection.status} />
        <span className="text-sm text-slate-500">
          Slack workspace {connection.external_team_id}
          {connection.last_verified_at &&
            ` · verified ${new Date(connection.last_verified_at).toLocaleString()}`}
        </span>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => setShowGroups((open) => !open)}>
            {showGroups ? "Hide groups" : "User groups"}
          </Button>
          {canManage && (
            <>
              <Button variant="ghost" onClick={() => verify.mutate()} disabled={verify.isPending}>
                {verify.isPending ? "Checking…" : "Test"}
              </Button>
              <Button
                variant="danger"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
              >
                Disconnect
              </Button>
            </>
          )}
        </div>
      </div>

      {!connection.has_user_token && (
        <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Installed without a user token. If this workspace restricts who may manage user
          groups, updates will fail — reinstall and approve the user permissions to add a
          fallback.
        </p>
      )}
      {connection.last_error && (
        <p className="mt-3 text-sm text-red-600">{connection.last_error}</p>
      )}
      {verify.data && (
        <p className={`mt-3 text-sm ${verify.data.ok ? "text-emerald-700" : "text-red-600"}`}>
          {verify.data.detail}
        </p>
      )}
      {showGroups && <Groups connectionId={connection.id} />}
    </Card>
  );
}

function Groups({ connectionId }: { connectionId: string }) {
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
    <div className="mt-4 border-t border-slate-100 pt-4">
      <div className="mb-2 flex items-center gap-3">
        <span className="text-sm font-medium text-slate-700">
          User groups {groups.data && `(${groups.data.length})`}
        </span>
        <Button
          variant="ghost"
          className="ml-auto"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
        >
          {refresh.isPending ? "Refreshing…" : "Refresh"}
        </Button>
      </div>
      {groups.error && <Alert>{errorMessage(groups.error)}</Alert>}
      {refresh.error && <Alert>{errorMessage(refresh.error)}</Alert>}
      {groups.data?.length === 0 && (
        <p className="text-sm text-slate-500">
          No user groups yet. Create one in Slack, then refresh.
        </p>
      )}
      <ul className="divide-y divide-slate-100">
        {groups.data?.map((group) => (
          <li key={group.id} className="flex items-center gap-3 py-2">
            <code className="text-sm text-slate-900">@{group.handle}</code>
            <span className="text-sm text-slate-500">{group.name}</span>
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
    <Card title={`Install ${provider.display_name}`}>
      {!provider.install_configured ? (
        <p className="text-sm text-slate-500">
          This deployment has no {provider.display_name} app configured.
        </p>
      ) : !canManage ? (
        <p className="text-sm text-slate-500">
          Ask an admin or owner to install {provider.display_name}.
        </p>
      ) : (
        <>
          <Button onClick={() => start.mutate()} disabled={start.isPending}>
            Add to {provider.display_name}
          </Button>
          <p className="mt-3 text-xs text-slate-500">
            Approve both the app and the user permissions. The user grant is the fallback for
            workspaces that restrict who may manage user groups — without it, updates fail
            there.
          </p>
          {start.error && (
            <div className="mt-3">
              <Alert>{errorMessage(start.error)}</Alert>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
