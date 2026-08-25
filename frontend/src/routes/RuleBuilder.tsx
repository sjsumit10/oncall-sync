import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Alert, Button, Card, Field } from "@/components/ui";
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
      <h1 className="text-xl font-semibold text-slate-900">New sync rule</h1>

      <Card>
        <form
          className="space-y-5"
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

          <Select
            label="Schedule"
            value={scheduleId}
            onChange={setScheduleId}
            required
            options={(schedules.data ?? []).map((s) => ({
              value: s.external_id,
              label: `${s.name} (${s.timezone})`,
            }))}
            empty="No schedules cached. Refresh them on the connections page."
          />

          <fieldset>
            <legend className="mb-1 text-sm font-medium text-slate-700">
              Escalation levels
            </legend>
            <div className="flex gap-4">
              {LEVELS.map((level) => (
                <label key={level} className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={levels.includes(level)}
                    onChange={(event) =>
                      setLevels((current) =>
                        event.target.checked
                          ? [...current, level].sort()
                          : current.filter((l) => l !== level),
                      )
                    }
                  />
                  Level {level}
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Level 1 is the person actually holding the pager. Selecting more than one includes
              everyone across those levels.
            </p>
          </fieldset>

          <Select
            label="User group to keep updated"
            value={groupId}
            onChange={setGroupId}
            required
            options={(groups.data ?? []).map((g) => ({
              value: g.external_id,
              label: `@${g.handle} — ${g.name}`,
            }))}
            empty="No user groups found. Create one in Slack, then refresh."
          />

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={notify}
              onChange={(event) => setNotify(event.target.checked)}
            />
            Announce handoffs in a channel
          </label>

          {notify && (
            <>
              <Select
                label="Channel"
                value={channelId}
                onChange={setChannelId}
                options={(channels.data ?? [])
                  .filter((c) => c.bot_is_member)
                  .map((c) => ({ value: c.external_id, label: `#${c.name}` }))}
                empty="No channels the app has joined. Invite it to a channel, then refresh."
              />
              <TemplateEditor value={template} onChange={setTemplate} />
              {template.trim() && <ResetTemplateButton onReset={() => setTemplate("")} />}
            </>
          )}

          <Field
            label="Fallback member (optional)"
            value={fallback}
            placeholder="Slack user ID, e.g. U01ABCDEF"
            onChange={(event) => setFallback(event.target.value)}
          />
          <p className="-mt-3 text-xs text-slate-500">
            Used when nobody resolves to a chat account. Slack refuses to leave a user group
            empty, so without this the handle is left unchanged instead.
          </p>

          {selectedHandle && (
            <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
              Mentioning <code className="text-slate-900">@{selectedHandle}</code> will notify
              whoever is on call.
            </p>
          )}

          {create.error && <Alert>{errorMessage(create.error)}</Alert>}

          <div className="flex gap-2">
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create rule"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => navigate("/rules")}>
              Cancel
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  empty,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  empty: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {options.length === 0 ? (
        <p className="text-sm text-slate-500">{empty}</p>
      ) : (
        <select
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          value={value}
          required={required}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Choose…</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </label>
  );
}
