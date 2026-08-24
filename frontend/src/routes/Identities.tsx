import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
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
      <h1 className="text-xl font-semibold text-slate-900">Identities</h1>

      <Card>
        <p className="text-sm text-slate-600">
          People are matched to chat accounts by email address. Anyone whose addresses differ —
          contractors, aliases, SSO variance — needs linking by hand, or they will be skipped at
          handoff.
        </p>
      </Card>

      {oncall.length === 0 || chat.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-600">
            Connect an on-call provider and a chat workspace first.
          </p>
        </Card>
      ) : (
        <Card>
          <label className="mb-4 flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={unmappedOnly}
              onChange={(event) => setUnmappedOnly(event.target.checked)}
            />
            Show only people without a link
          </label>

          {directory.isPending && <p className="text-sm text-slate-500">Loading directory…</p>}
          {directory.error && <Alert>{errorMessage(directory.error)}</Alert>}
          {directory.data?.length === 0 && (
            <p className="text-sm text-emerald-700">
              {unmappedOnly ? "Everyone is linked." : "Nobody in the directory."}
            </p>
          )}

          <ul className="divide-y divide-slate-100">
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
          <p className="truncate text-sm font-medium text-slate-900">
            {entry.provider_user.name}
          </p>
          <p className="truncate text-sm text-slate-500">
            {entry.provider_user.email ?? "no email on record"}
          </p>
        </div>

        {entry.link ? (
          <>
            <span className="text-sm text-slate-600">
              → {entry.link.chat_user_name ?? entry.link.chat_user_id}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
              {entry.link.source === "manual" ? "manual" : "matched by email"}
            </span>
            {canManage && (
              <Button
                variant="danger"
                className="ml-auto"
                onClick={() => unlink.mutate()}
                disabled={unlink.isPending}
              >
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
              <input
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
                placeholder="Slack user ID"
                value={chatUserId}
                onChange={(event) => setChatUserId(event.target.value)}
                required
              />
              <Button type="submit" disabled={link.isPending}>
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
