import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Trash2, UserPlus } from "lucide-react";
import { useState } from "react";

import { Field } from "@/components/field";
import { PageHeader } from "@/components/page";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import type { Invite, InviteCreated, Organization, Session, User, UserRole } from "@/lib/types";
import { errorMessage } from "./Login";

export default function Settings() {
  const { data: session } = useSession();
  const isOwner = session?.user.role === "owner";
  const canManage = isOwner || session?.user.role === "admin";

  return (
    <div className="space-y-8">
      <PageHeader title="Settings" description="Manage your organization, members and invites." />
      {isOwner && session && <OrganizationSettings organization={session.organization} />}
      <Members canManage={canManage} currentUserId={session?.user.id} />
      {canManage && <Invites isOwner={isOwner} />}
    </div>
  );
}

function OrganizationSettings({ organization }: { organization: Organization }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(organization.name);

  const update = useMutation({
    mutationFn: () => api.patch<Organization>("/org", { name }),
    onSuccess: (org) => {
      queryClient.setQueryData<Session | null>(["session"], (session) =>
        session ? { ...session, organization: org } : session,
      );
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Organization</CardTitle>
        <CardDescription>The name your team sees across On-Call Sync.</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            update.mutate();
          }}
        >
          <div className="min-w-56 flex-1">
            <Field
              label="Organization name"
              required
              minLength={2}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={update.isPending || name.trim() === organization.name}>
            Save
          </Button>
        </form>
        {update.error && (
          <div className="mt-3">
            <Alert>{errorMessage(update.error)}</Alert>
          </div>
        )}
      </CardContent>
    </Card>
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
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>Everyone with access to this organization.</CardDescription>
      </CardHeader>
      <CardContent>
        {remove.error && (
          <div className="mb-3">
            <Alert>{errorMessage(remove.error)}</Alert>
          </div>
        )}
        <ul className="divide-y divide-border">
          {members.data?.map((member) => (
            <li key={member.id} className="flex items-center gap-3 py-3">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                {member.name.trim().charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">{member.name}</p>
                <p className="truncate text-sm text-muted-foreground">{member.email}</p>
              </div>
              <RoleBadge role={member.role} className="ml-auto" />
              {canManage && member.id !== currentUserId && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground hover:text-destructive"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(member.id)}
                  aria-label={`Remove ${member.name}`}
                >
                  <Trash2 className="size-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
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
    <Card>
      <CardHeader>
        <CardTitle>Pending invites</CardTitle>
        <CardDescription>Invite teammates by email — they'll get a one-time link.</CardDescription>
      </CardHeader>
      <CardContent>
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
          <div className="w-36 space-y-1.5">
            <Label>Role</Label>
            <Select value={role} onValueChange={(value) => setRole(value as UserRole)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">Member</SelectItem>
                {isOwner && <SelectItem value="admin">Admin</SelectItem>}
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={create.isPending}>
            <UserPlus className="size-4" />
            Invite
          </Button>
        </form>

        {create.error && (
          <div className="mt-3">
            <Alert>{errorMessage(create.error)}</Alert>
          </div>
        )}
        {lastLink && (
          <p className="mt-3 flex items-start gap-2 break-all rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
            <Mail className="mt-0.5 size-4 shrink-0" />
            <span>
              Share this link — it is shown only once:{" "}
              <span className="font-mono text-foreground">{lastLink}</span>
            </span>
          </p>
        )}

        <ul className="mt-4 divide-y divide-border">
          {invites.data?.length === 0 && (
            <li className="py-3 text-sm text-muted-foreground">None.</li>
          )}
          {invites.data?.map((invite) => (
            <li key={invite.id} className="flex items-center gap-3 py-3">
              <span className="text-sm text-foreground">{invite.email}</span>
              <RoleBadge role={invite.role} />
              <span className="text-sm text-muted-foreground">
                expires {new Date(invite.expires_at).toLocaleDateString()}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto text-muted-foreground hover:text-destructive"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate(invite.id)}
                aria-label={`Revoke invite for ${invite.email}`}
              >
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function RoleBadge({ role, className }: { role: string; className?: string }) {
  return (
    <Badge variant={role === "owner" ? "default" : role === "admin" ? "secondary" : "outline"} className={className}>
      {role}
    </Badge>
  );
}
