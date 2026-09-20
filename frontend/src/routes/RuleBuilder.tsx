import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Field } from "@/components/field";
import { PageHeader } from "@/components/page";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useChannels, useConnections, useGroups, useSchedules } from "@/lib/connections";
import type { ChatChannel, SyncRule } from "@/lib/types";
import { errorMessage } from "./Login";
import { ResetTemplateButton, TemplateEditor } from "./TemplateEditor";

const LEVELS = [1, 2, 3];

export default function RuleBuilder() {
  const navigate = useNavigate();
  const { ruleId } = useParams();
  const isEdit = Boolean(ruleId);
  const { oncall, chat } = useConnections();

  const existing = useQuery({
    queryKey: ["rule", ruleId],
    queryFn: () => api.get<SyncRule>(`/rules/${ruleId}`),
    enabled: isEdit,
  });

  const [oncallId, setOncallId] = useState("");
  const [chatId, setChatId] = useState("");
  const [name, setName] = useState("");
  const [scheduleId, setScheduleId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [levels, setLevels] = useState<number[]>([1]);
  const [notify, setNotify] = useState(true);
  const [fallback, setFallback] = useState("");
  const [template, setTemplate] = useState("");

  // Default to the only connection of each kind, which is the normal case —
  // but only when creating. Editing seeds these from the rule itself below.
  useEffect(() => {
    if (isEdit) return;
    if (!oncallId && oncall.length > 0) setOncallId(oncall[0].id);
  }, [isEdit, oncall, oncallId]);
  useEffect(() => {
    if (isEdit) return;
    if (!chatId && chat.length > 0) setChatId(chat[0].id);
  }, [isEdit, chat, chatId]);

  // Seed the form once the rule loads. A ref (not state) so this never fires
  // twice and clobbers an in-progress edit if the query refetches.
  const seeded = useRef(false);
  useEffect(() => {
    if (!existing.data || seeded.current) return;
    seeded.current = true;
    const rule = existing.data;
    setOncallId(rule.oncall_connection_id);
    setChatId(rule.chat_connection_id);
    setName(rule.name);
    setScheduleId(rule.schedule_external_id);
    setGroupId(rule.group_external_id);
    setChannelId(rule.notify_channel_external_id ?? "");
    setLevels(rule.escalation_levels);
    setNotify(rule.notify_on_change);
    setFallback(rule.fallback_chat_user_id ?? "");
    setTemplate(rule.message_template ?? "");
  }, [existing.data]);

  const schedules = useSchedules(oncallId || undefined);
  const groups = useGroups(chatId || undefined);
  const channels = useChannels(chatId || undefined);
  const chatKind = chat.find((c) => c.id === chatId)?.kind;
  const isTeams = chatKind === "teams";

  const queryClient = useQueryClient();

  // The channel list only ever updates when this is called — an invite sent
  // in Slack after the cache was first populated is otherwise never noticed.
  const refreshChannels = useMutation({
    mutationFn: () =>
      api.get<ChatChannel[]>(`/chat/connections/${chatId}/channels?refresh=true`),
    onSuccess: (data) => queryClient.setQueryData(["chat-channels", chatId], data),
  });

  const save = useMutation({
    mutationFn: () => {
      if (isEdit) {
        return api.patch<SyncRule>(`/rules/${ruleId}`, {
          name,
          escalation_levels: levels,
          notify_channel_external_id: notify && channelId ? channelId : null,
          notify_on_change: notify,
          message_template: template.trim() || null,
          fallback_chat_user_id: fallback.trim() || null,
        });
      }
      return api.post<SyncRule>("/rules", {
        name,
        oncall_connection_id: oncallId,
        schedule_external_id: scheduleId,
        escalation_levels: levels,
        chat_connection_id: chatId,
        group_external_id: groupId,
        notify_channel_external_id: notify && channelId ? channelId : null,
        notify_on_change: notify,
        message_template: template.trim() || null,
        fallback_chat_user_id: fallback.trim() || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      navigate("/rules");
    },
  });

  const selectedHandle = groups.data?.find((g) => g.external_id === groupId)?.handle;

  if (isEdit && existing.isPending) {
    return <p className="text-sm text-muted-foreground">Loading rule…</p>;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={isEdit ? "Edit sync rule" : "New sync rule"}
        description="Map a schedule to a chat group handle."
      />

      <Card>
        <CardContent className="pt-6">
          <form
            className="space-y-6"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate();
            }}
          >
            <Field
              label="Rule name"
              required
              value={name}
              placeholder="DevOps on-call"
              onChange={(event) => setName(event.target.value)}
            />

            {isEdit ? (
              <ReadOnlyField
                label="Schedule"
                value={(() => {
                  const schedule = schedules.data?.find((s) => s.external_id === scheduleId);
                  return schedule ? `${schedule.name} (${schedule.timezone})` : scheduleId;
                })()}
                hint="Can't be changed after creation — delete and recreate the rule instead."
              />
            ) : (
              <PickerField
                label="Schedule"
                value={scheduleId}
                onChange={setScheduleId}
                placeholder="Choose a schedule…"
                options={(schedules.data ?? []).map((s) => ({
                  value: s.external_id,
                  label: `${s.name} (${s.timezone})`,
                }))}
                empty="No schedules cached. Refresh them on the connections page."
              />
            )}

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-foreground">Escalation levels</legend>
              <div className="flex gap-5">
                {LEVELS.map((level) => (
                  <label key={level} className="flex items-center gap-2 text-sm text-foreground">
                    <Checkbox
                      checked={levels.includes(level)}
                      onCheckedChange={(checked) =>
                        setLevels((current) =>
                          checked
                            ? [...current, level].sort()
                            : current.filter((l) => l !== level),
                        )
                      }
                    />
                    Level {level}
                  </label>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Level 1 is the person actually holding the pager. Selecting more than one includes
                everyone across those levels.
              </p>
            </fieldset>

            {isEdit ? (
              <ReadOnlyField
                label="User group to keep updated"
                value={(() => {
                  const group = groups.data?.find((g) => g.external_id === groupId);
                  return group ? `@${group.handle} — ${group.name}` : groupId;
                })()}
                hint="Can't be changed after creation — delete and recreate the rule instead."
              />
            ) : (
              <PickerField
                label="User group to keep updated"
                value={groupId}
                onChange={setGroupId}
                placeholder="Choose a group…"
                options={(groups.data ?? []).map((g) => ({
                  value: g.external_id,
                  label: `@${g.handle} — ${g.name}`,
                }))}
                empty={
                  isTeams
                    ? "No tags found. Create one in Teams, then refresh."
                    : "No user groups found. Create one in Slack, then refresh."
                }
              />
            )}

            <label className="flex items-center justify-between rounded-lg border border-border px-4 py-3">
              <span>
                <span className="block text-sm font-medium text-foreground">
                  Announce handoffs in a channel
                </span>
                <span className="block text-xs text-muted-foreground">
                  Post a message whenever who's on call changes.
                </span>
              </span>
              <Switch checked={notify} onCheckedChange={setNotify} />
            </label>

            {notify && (
              <div className="space-y-4 rounded-lg border border-border p-4">
                <PickerField
                  label="Channel"
                  value={channelId}
                  onChange={setChannelId}
                  placeholder="Choose a channel…"
                  options={(channels.data ?? [])
                    .filter((c) => c.bot_is_member)
                    .map((c) => ({ value: c.external_id, label: `#${c.name}` }))}
                  empty="No channels the app has joined. Invite it in Slack, then refresh below."
                  action={
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => refreshChannels.mutate()}
                      disabled={refreshChannels.isPending || !chatId}
                    >
                      <RefreshCw
                        className={`size-3.5 ${refreshChannels.isPending ? "animate-spin" : ""}`}
                      />
                      {refreshChannels.isPending ? "Refreshing…" : "Refresh"}
                    </Button>
                  }
                />
                {refreshChannels.error && <Alert>{errorMessage(refreshChannels.error)}</Alert>}
                <TemplateEditor value={template} onChange={setTemplate} />
                {template.trim() && <ResetTemplateButton onReset={() => setTemplate("")} />}
              </div>
            )}

            <Field
              label="Fallback member (optional)"
              value={fallback}
              placeholder={
                isTeams ? "Microsoft user id, e.g. 3fa8...c4e5" : "Slack user ID, e.g. U01ABCDEF"
              }
              onChange={(event) => setFallback(event.target.value)}
            />
            <p className="-mt-3 text-xs text-muted-foreground">
              Used when nobody resolves to a chat account. {isTeams ? "Teams" : "Slack"} refuses to
              leave a {isTeams ? "tag" : "user group"} empty, so without this the handle is left
              unchanged instead.
            </p>

            {selectedHandle && (
              <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
                Mentioning <code className="text-foreground">@{selectedHandle}</code> will notify
                whoever is on call.
              </p>
            )}

            {save.error && <Alert>{errorMessage(save.error)}</Alert>}

            <div className="flex gap-2">
              <Button type="submit" disabled={save.isPending}>
                {save.isPending
                  ? isEdit
                    ? "Saving…"
                    : "Creating…"
                  : isEdit
                    ? "Save changes"
                    : "Create rule"}
              </Button>
              <Button type="button" variant="outline" onClick={() => navigate("/rules")}>
                Cancel
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function ReadOnlyField({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-foreground">
        {value}
      </p>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

function PickerField({
  label,
  value,
  onChange,
  options,
  empty,
  placeholder,
  action,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  empty: string;
  placeholder: string;
  action?: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        {action}
      </div>
      {options.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger>
            <SelectValue placeholder={placeholder} />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}
