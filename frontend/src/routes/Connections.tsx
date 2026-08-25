import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, RefreshCw, Unplug, Zap } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Field } from "@/components/field";
import { SectionHeading } from "@/components/page";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight text-foreground">Connections</h1>

      {connected && (
        <p className="flex items-center gap-2 rounded-md bg-success/10 px-3 py-2 text-sm text-success">
          <CheckCircle2 className="size-4 shrink-0" />
          {connected} connected. <DismissLink onClick={() => setParams({})} />
        </p>
      )}
      {callbackError && (
        <Alert>
          Could not complete the connection ({callbackError}).{" "}
          <DismissLink onClick={() => setParams({})} />
        </Alert>
      )}

      <div className="space-y-4">
        <SectionHeading title="On-call provider" hint="Where schedules come from." />
        {connections.data?.map((connection) => (
          <ConnectionCard key={connection.id} connection={connection} canManage={canManage} />
        ))}
        {providers.data
          ?.filter((provider) => !connections.data?.some((c) => c.kind === provider.kind))
          .map((provider) => (
            <ConnectCard key={provider.kind} provider={provider} canManage={canManage} />
          ))}
      </div>

      <div className="space-y-4">
        <SectionHeading
          title="Chat workspace"
          hint="Where the group handle lives, and where handoffs are announced."
        />
        <ChatSection canManage={canManage} />
      </div>
    </div>
  );
}

function DismissLink({ onClick }: { onClick: () => void }) {
  return (
    <button className="font-medium underline underline-offset-4" onClick={onClick}>
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
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>{connection.display_name}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={connection.status} />
          <span className="text-sm text-muted-foreground">
            {connection.auth_mode === "oauth" ? "OAuth" : "API key"}
            {connection.last_verified_at &&
              ` · verified ${new Date(connection.last_verified_at).toLocaleString()}`}
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowSchedules((open) => !open)}>
              {showSchedules ? "Hide schedules" : "Schedules"}
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

        {connection.last_error && (
          <p className="mt-3 text-sm text-destructive">{connection.last_error}</p>
        )}
        {verify.data && (
          <p className={`mt-3 text-sm ${verify.data.ok ? "text-success" : "text-destructive"}`}>
            {verify.data.detail}
          </p>
        )}
        {showSchedules && <Schedules connectionId={connection.id} />}
      </CardContent>
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
    <div className="mt-4 border-t border-border pt-4">
      <div className="mb-2 flex items-center gap-3">
        <span className="text-sm font-medium text-foreground">
          Schedules {schedules.data && `(${schedules.data.length})`}
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
      {schedules.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {schedules.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">No schedules found in this account.</p>
      )}
      <ul className="divide-y divide-border">
        {schedules.data?.map((schedule) => (
          <li key={schedule.id} className="flex items-center gap-3 py-2">
            <span className="text-sm text-foreground">{schedule.name}</span>
            <span className="text-xs text-muted-foreground">{schedule.timezone}</span>
            <code className="ml-auto text-xs text-muted-foreground">{schedule.external_id}</code>
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
      <Card className="border-dashed">
        <CardHeader className="pb-4">
          <CardTitle>Connect {provider.display_name}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Ask an admin or owner to connect this provider.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-dashed">
      <CardHeader className="pb-4">
        <CardTitle>Connect {provider.display_name}</CardTitle>
      </CardHeader>
      <CardContent>
        {provider.supports_oauth && provider.oauth_configured && (
          <div className="mb-4">
            <Button onClick={() => startOauth.mutate()} disabled={startOauth.isPending}>
              <Zap className="size-4" />
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
            <Button type="submit" variant="outline" disabled={connectKey.isPending}>
              <KeyRound className="size-4" />
              {connectKey.isPending ? "Verifying…" : "Connect"}
            </Button>
          </form>
        )}

        <p className="mt-3 text-xs text-muted-foreground">
          The key is verified against {provider.display_name} before it is stored, and is
          encrypted at rest.
        </p>
        {connectKey.error && (
          <div className="mt-3">
            <Alert>{errorMessage(connectKey.error)}</Alert>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
