import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

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
import type { SyncRule } from "@/lib/types";
import { errorMessage } from "./Login";
import { ResetTemplateButton, TemplateEditor } from "./TemplateEditor";

const LEVELS = [1, 2, 3];

export default function RuleBuilder() {
  const navigate = useNavigate();
  const { oncall, chat } = useConnections();

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

  // Default to the only connection of each kind, which is the normal case.
  useEffect(() => {
    if (!oncallId && oncall.length > 0) setOncallId(oncall[0].id);
  }, [oncall, oncallId]);
  useEffect(() => {
    if (!chatId && chat.length > 0) setChatId(chat[0].id);
  }, [chat, chatId]);

  const schedules = useSchedules(oncallId || undefined);
  const groups = useGroups(chatId || undefined);
  const channels = useChannels(chatId || undefined);

  const create = useMutation({
    mutationFn: () =>
      api.post<SyncRule>("/rules", {
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
      }),
    onSuccess: () => navigate("/rules"),
  });

  const selectedHandle = groups.data?.find((g) => g.external_id === groupId)?.handle;

  return (
    <div className="space-y-6">
      <PageHeader title="New sync rule" description="Map a schedule to a chat group handle." />

      <Card>
        <CardContent className="pt-6">
          <form
            className="space-y-6"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <Field
              label="Rule name"
              required
              value={name}
              placeholder="DevOps on-call"
              onChange={(event) => setName(event.target.value)}
            />

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

            <PickerField
              label="User group to keep updated"
              value={groupId}
              onChange={setGroupId}
              placeholder="Choose a group…"
              options={(groups.data ?? []).map((g) => ({
                value: g.external_id,
                label: `@${g.handle} — ${g.name}`,
              }))}
              empty="No user groups found. Create one in Slack, then refresh."
            />

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
                  empty="No channels the app has joined. Invite it to a channel, then refresh."
                />
                <TemplateEditor value={template} onChange={setTemplate} />
                {template.trim() && <ResetTemplateButton onReset={() => setTemplate("")} />}
              </div>
            )}

            <Field
              label="Fallback member (optional)"
              value={fallback}
              placeholder="Slack user ID, e.g. U01ABCDEF"
              onChange={(event) => setFallback(event.target.value)}
            />
            <p className="-mt-3 text-xs text-muted-foreground">
              Used when nobody resolves to a chat account. Slack refuses to leave a user group
              empty, so without this the handle is left unchanged instead.
            </p>

            {selectedHandle && (
              <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
                Mentioning <code className="text-foreground">@{selectedHandle}</code> will notify
                whoever is on call.
              </p>
            )}

            {create.error && <Alert>{errorMessage(create.error)}</Alert>}

            <div className="flex gap-2">
              <Button type="submit" disabled={create.isPending}>
                {create.isPending ? "Creating…" : "Create rule"}
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

function PickerField({
  label,
  value,
  onChange,
  options,
  empty,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  empty: string;
  placeholder: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
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
