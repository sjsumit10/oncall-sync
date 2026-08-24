import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Button, Card, Field, RoleBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import type { Invite, InviteCreated, User, UserRole } from "@/lib/types";
import { errorMessage } from "./Login";

export default function Settings() {
  const { data: session } = useSession();
  const canManage = session?.user.role === "owner" || session?.user.role === "admin";

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">Settings</h1>
      <Members canManage={canManage} currentUserId={session?.user.id} />
      {canManage && <Invites isOwner={session?.user.role === "owner"} />}
    </div>
  );
}

function Members({ canManage, currentUserId }: { canManage: boolean; currentUserId?: string }) {
  const queryClient = useQueryClient();
  const members = useQuery({
    queryKey: ["members"],
    queryFn: () => api.get<User[]>("/org/members"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del<void>(`/org/members/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["members"] }),
  });

  return (
    <Card title="Members">
      {remove.error && <Alert>{errorMessage(remove.error)}</Alert>}
      <ul className="divide-y divide-slate-100">
        {members.data?.map((member) => (
          <li key={member.id} className="flex items-center gap-3 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-900">{member.name}</p>
              <p className="truncate text-sm text-slate-500">{member.email}</p>
            </div>
            <RoleBadge role={member.role} />
            {canManage && member.id !== currentUserId && (
              <Button
                variant="danger"
                className="ml-auto"
                disabled={remove.isPending}
                onClick={() => remove.mutate(member.id)}
              >
                Remove
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Invites({ isOwner }: { isOwner: boolean }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("member");
  const [lastLink, setLastLink] = useState<string | null>(null);

  const invites = useQuery({
    queryKey: ["invites"],
    queryFn: () => api.get<Invite[]>("/org/invites"),
  });

  const create = useMutation({
    mutationFn: () => api.post<InviteCreated>("/org/invites", { email, role }),
    onSuccess: (created) => {
      // There is no email delivery yet, so the link is shown once, here.
      setLastLink(created.accept_url);
      setEmail("");
      queryClient.invalidateQueries({ queryKey: ["invites"] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.del<void>(`/org/invites/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invites"] }),
  });

  return (
    <Card title="Pending invites">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <div className="min-w-56 flex-1">
          <Field
            label="Email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Role</span>
          <select
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
          >
            <option value="member">Member</option>
            {isOwner && <option value="admin">Admin</option>}
          </select>
        </label>
        <Button type="submit" disabled={create.isPending}>
          Invite
        </Button>
      </form>

      {create.error && (
        <div className="mt-3">
          <Alert>{errorMessage(create.error)}</Alert>
        </div>
      )}
      {lastLink && (
        <p className="mt-3 break-all rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
          Share this link — it is shown only once:{" "}
          <span className="font-mono text-slate-900">{lastLink}</span>
        </p>
      )}

      <ul className="mt-4 divide-y divide-slate-100">
        {invites.data?.length === 0 && <li className="py-3 text-sm text-slate-500">None.</li>}
        {invites.data?.map((invite) => (
          <li key={invite.id} className="flex items-center gap-3 py-3">
            <span className="text-sm text-slate-900">{invite.email}</span>
            <RoleBadge role={invite.role} />
            <span className="text-sm text-slate-400">
              expires {new Date(invite.expires_at).toLocaleDateString()}
            </span>
            <Button
              variant="danger"
              className="ml-auto"
              disabled={revoke.isPending}
              onClick={() => revoke.mutate(invite.id)}
            >
              Revoke
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
