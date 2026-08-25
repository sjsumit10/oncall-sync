import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Link2, Unlink } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState, PageHeader } from "@/components/page";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { useConnections } from "@/lib/connections";
import type { DirectoryEntry } from "@/lib/types";
import { errorMessage } from "./Login";

export default function Identities() {
  const { data: session } = useSession();
  const canManage = session?.user.role === "owner" || session?.user.role === "admin";
  const { oncall, chat } = useConnections();

  const [oncallId, setOncallId] = useState("");
  const [chatId, setChatId] = useState("");
  const [unmappedOnly, setUnmappedOnly] = useState(true);

  useEffect(() => {
    if (!oncallId && oncall.length > 0) setOncallId(oncall[0].id);
  }, [oncall, oncallId]);
  useEffect(() => {
    if (!chatId && chat.length > 0) setChatId(chat[0].id);
  }, [chat, chatId]);

  const query = `?oncall_connection_id=${oncallId}&chat_connection_id=${chatId}&unmapped_only=${unmappedOnly}`;
  const directory = useQuery({
    queryKey: ["identities", oncallId, chatId, unmappedOnly],
    queryFn: () => api.get<DirectoryEntry[]>(`/identities${query}`),
    enabled: Boolean(oncallId && chatId),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Identities"
        description="People are matched to chat accounts by email address. Anyone whose addresses differ — contractors, aliases, SSO variance — needs linking by hand, or they will be skipped at handoff."
      />

      {oncall.length === 0 || chat.length === 0 ? (
        <EmptyState
          icon={Link2}
          title="Connect your tools first"
          description="Connect an on-call provider and a chat workspace to see your directory."
        />
      ) : (
        <Card>
          <CardContent className="pt-6">
            <label className="mb-4 flex items-center gap-2 text-sm text-foreground">
              <Checkbox
                checked={unmappedOnly}
                onCheckedChange={(checked) => setUnmappedOnly(checked === true)}
              />
              Show only people without a link
            </label>

            {directory.isPending && (
              <p className="text-sm text-muted-foreground">Loading directory…</p>
            )}
            {directory.error && <Alert>{errorMessage(directory.error)}</Alert>}
            {directory.data?.length === 0 && (
              <p className="flex items-center gap-2 text-sm text-success">
                <CheckCircle2 className="size-4" />
                {unmappedOnly ? "Everyone is linked." : "Nobody in the directory."}
              </p>
            )}

            <ul className="divide-y divide-border">
              {directory.data?.map((entry) => (
                <Row
                  key={entry.provider_user.external_id}
                  entry={entry}
                  canManage={canManage}
                  oncallId={oncallId}
                  chatId={chatId}
                />
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Row({
  entry,
  canManage,
  oncallId,
  chatId,
}: {
  entry: DirectoryEntry;
  canManage: boolean;
  oncallId: string;
  chatId: string;
}) {
  const queryClient = useQueryClient();
  const [chatUserId, setChatUserId] = useState("");
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["identities"] });

  const link = useMutation({
    mutationFn: () =>
      api.post("/identities", {
        oncall_connection_id: oncallId,
        chat_connection_id: chatId,
        provider_user_id: entry.provider_user.external_id,
        chat_user_id: chatUserId.trim(),
      }),
    onSuccess: () => {
      setChatUserId("");
      invalidate();
    },
  });
  const unlink = useMutation({
    mutationFn: () => api.del<void>(`/identities/${entry.link?.id}`),
    onSuccess: invalidate,
  });

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {entry.provider_user.name}
          </p>
          <p className="truncate text-sm text-muted-foreground">
            {entry.provider_user.email ?? "no email on record"}
          </p>
        </div>

        {entry.link ? (
          <>
            <span className="text-sm text-muted-foreground">
              → {entry.link.chat_user_name ?? entry.link.chat_user_id}
            </span>
            <Badge variant="secondary">
              {entry.link.source === "manual" ? "manual" : "matched by email"}
            </Badge>
            {canManage && (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto text-muted-foreground hover:text-destructive"
                onClick={() => unlink.mutate()}
                disabled={unlink.isPending}
              >
                <Unlink className="size-4" />
                Unlink
              </Button>
            )}
          </>
        ) : (
          canManage && (
            <form
              className="ml-auto flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                link.mutate();
              }}
            >
              <Label htmlFor={`link-${entry.provider_user.external_id}`} className="sr-only">
                Slack user ID
              </Label>
              <Input
                id={`link-${entry.provider_user.external_id}`}
                className="h-8 w-40"
                placeholder="Slack user ID"
                value={chatUserId}
                onChange={(event) => setChatUserId(event.target.value)}
                required
              />
              <Button type="submit" size="sm" disabled={link.isPending}>
                Link
              </Button>
            </form>
          )
        )}
      </div>
      {link.error && (
        <div className="mt-2">
          <Alert>{errorMessage(link.error)}</Alert>
        </div>
      )}
    </li>
  );
}
