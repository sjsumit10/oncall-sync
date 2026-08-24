import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Alert, Button, Card, Field } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import type {
  ConnectionHealth,
  OncallConnection,
  OncallProvider,
  OncallSchedule,
} from "@/lib/types";
import { ChatSection } from "./ChatSection";
import { errorMessage } from "./Login";
import { StatusBadge } from "./StatusBadge";

export default function Connections() {
  const { data: session } = useSession();
  const canManage = session?.user.role === "owner" || session?.user.role === "admin";
  const [params, setParams] = useSearchParams();

  const providers = useQuery({
    queryKey: ["oncall-providers"],
    queryFn: () => api.get<OncallProvider[]>("/oncall/providers"),
  });
  const connections = useQuery({
    queryKey: ["oncall-connections"],
    queryFn: () => api.get<OncallConnection[]>("/oncall/connections"),
  });

  // The OAuth callback redirects back here with the outcome in the query string.
  const connected = params.get("connected") ?? params.get("installed");
  const callbackError = params.get("error");

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">Connections</h1>

      {connected && (
        <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {connected} connected. <DismissLink onClick={() => setParams({})} />
        </p>
      )}
      {callbackError && (
        <Alert>
          Could not complete the connection ({callbackError}).{" "}
          <DismissLink onClick={() => setParams({})} />
        </Alert>
      )}

      <SectionHeading
        title="On-call provider"
        hint="Where schedules come from."
      />
      {connections.data?.map((connection) => (
        <ConnectionCard key={connection.id} connection={connection} canManage={canManage} />
      ))}
      {providers.data
        ?.filter((provider) => !connections.data?.some((c) => c.kind === provider.kind))
        .map((provider) => (
          <ConnectCard key={provider.kind} provider={provider} canManage={canManage} />
        ))}

      <SectionHeading
        title="Chat workspace"
        hint="Where the group handle lives, and where handoffs are announced."
      />
      <ChatSection canManage={canManage} />
    </div>
  );
}

function DismissLink({ onClick }: { onClick: () => void }) {
  return (
    <button className="underline" onClick={onClick}>
      Dismiss
    </button>
  );
}

function ConnectionCard({
  connection,
  canManage,
}: {
  connection: OncallConnection;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [showSchedules, setShowSchedules] = useState(false);

  const verify = useMutation({
    mutationFn: () =>
      api.post<ConnectionHealth>(`/oncall/connections/${connection.id}/verify`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["oncall-connections"] }),
  });

  const disconnect = useMutation({
    mutationFn: () => api.del<void>(`/oncall/connections/${connection.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["oncall-connections"] }),
  });

  return (
    <Card title={connection.display_name}>
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={connection.status} />
        <span className="text-sm text-slate-500">
          {connection.auth_mode === "oauth" ? "OAuth" : "API key"}
          {connection.last_verified_at &&
            ` · verified ${new Date(connection.last_verified_at).toLocaleString()}`}
        </span>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => setShowSchedules((open) => !open)}>
            {showSchedules ? "Hide schedules" : "Schedules"}
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

      {connection.last_error && (
        <p className="mt-3 text-sm text-red-600">{connection.last_error}</p>
      )}
      {verify.data && (
        <p className={`mt-3 text-sm ${verify.data.ok ? "text-emerald-700" : "text-red-600"}`}>
          {verify.data.detail}
        </p>
      )}
      {showSchedules && <Schedules connectionId={connection.id} />}
    </Card>
  );
}

function Schedules({ connectionId }: { connectionId: string }) {
  const queryClient = useQueryClient();
  const key = ["oncall-schedules", connectionId];

  const schedules = useQuery({
    queryKey: key,
    queryFn: () => api.get<OncallSchedule[]>(`/oncall/connections/${connectionId}/schedules`),
  });
  const refresh = useMutation({
    mutationFn: () =>
      api.get<OncallSchedule[]>(`/oncall/connections/${connectionId}/schedules?refresh=true`),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });

  return (
    <div className="mt-4 border-t border-slate-100 pt-4">
      <div className="mb-2 flex items-center gap-3">
        <span className="text-sm font-medium text-slate-700">
          Schedules {schedules.data && `(${schedules.data.length})`}
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
      {schedules.isPending && <p className="text-sm text-slate-500">Loading…</p>}
      {schedules.data?.length === 0 && (
        <p className="text-sm text-slate-500">No schedules found in this account.</p>
      )}
      <ul className="divide-y divide-slate-100">
        {schedules.data?.map((schedule) => (
          <li key={schedule.id} className="flex items-center gap-3 py-2">
            <span className="text-sm text-slate-900">{schedule.name}</span>
            <span className="text-xs text-slate-400">{schedule.timezone}</span>
            <code className="ml-auto text-xs text-slate-400">{schedule.external_id}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ConnectCard({
  provider,
  canManage,
}: {
  provider: OncallProvider;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");

  const startOauth = useMutation({
    mutationFn: () =>
      api.post<{ authorize_url: string }>(`/oncall/connections/${provider.kind}/oauth/start`),
    onSuccess: ({ authorize_url }) => {
      window.location.href = authorize_url;
    },
  });

  const connectKey = useMutation({
    mutationFn: () =>
      api.post<OncallConnection>("/oncall/connections", {
        kind: provider.kind,
        api_key: apiKey,
        display_name: provider.display_name,
      }),
    onSuccess: () => {
      setApiKey("");
      queryClient.invalidateQueries({ queryKey: ["oncall-connections"] });
    },
  });

  if (!canManage) {
    return (
      <Card title={`Connect ${provider.display_name}`}>
        <p className="text-sm text-slate-500">Ask an admin or owner to connect this provider.</p>
      </Card>
    );
  }

  return (
    <Card title={`Connect ${provider.display_name}`}>
      {provider.supports_oauth && provider.oauth_configured && (
        <div className="mb-4">
          <Button onClick={() => startOauth.mutate()} disabled={startOauth.isPending}>
            Connect with {provider.display_name}
          </Button>
          {startOauth.error && (
            <div className="mt-2">
              <Alert>{errorMessage(startOauth.error)}</Alert>
            </div>
          )}
        </div>
      )}

      {provider.auth_modes.includes("api_key") && (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            connectKey.mutate();
          }}
        >
          <div className="min-w-64 flex-1">
            <Field
              label={
                provider.oauth_configured
                  ? "Or paste a read-only API key"
                  : "Read-only API key"
              }
              type="password"
              autoComplete="off"
              required
              minLength={8}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={connectKey.isPending}>
            {connectKey.isPending ? "Verifying…" : "Connect"}
          </Button>
        </form>
      )}

      <p className="mt-3 text-xs text-slate-500">
        The key is verified against {provider.display_name} before it is stored, and is
        encrypted at rest.
      </p>
      {connectKey.error && (
        <div className="mt-3">
          <Alert>{errorMessage(connectKey.error)}</Alert>
        </div>
      )}
    </Card>
  );
}


function SectionHeading({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="pt-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      <p className="text-sm text-slate-500">{hint}</p>
    </div>
  );
}
