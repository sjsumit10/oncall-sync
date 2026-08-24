import { Alert } from "@/components/ui";
import type { RulePreview } from "@/lib/types";

/** The dry run. Shares its evaluation with the reconciler, so this is what will happen. */
export function RulePreviewPanel({ preview }: { preview: RulePreview }) {
  const noChange =
    preview.would_write && preview.would_add.length === 0 && preview.would_remove.length === 0;

  return (
    <div className="mt-4 space-y-3 rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium text-slate-700">On call for</span>
        <span className="text-sm text-slate-900">{preview.schedule_name}</span>
        {preview.next_change_at && (
          <span className="ml-auto text-xs text-slate-500">
            next handoff {new Date(preview.next_change_at).toLocaleString()}
          </span>
        )}
      </div>

      {preview.resolved.length > 0 && (
        <ul className="space-y-1">
          {preview.resolved.map((member) => (
            <li key={member.chat_user_id} className="text-sm text-slate-900">
              {member.provider_user.name}
              <span className="text-slate-500">
                {" → "}
                {member.chat_user_name ?? member.chat_user_id}
              </span>
              {member.source === "manual" && (
                <span className="ml-2 text-xs text-slate-400">manually linked</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {preview.used_fallback && (
        <p className="text-sm text-amber-800">
          Using the fallback member — Slack does not allow an empty user group.
        </p>
      )}

      {preview.problems.map((problem) => (
        <Alert key={problem}>{problem}</Alert>
      ))}

      {!preview.would_write ? (
        <p className="text-sm text-slate-600">
          The handle will be left exactly as it is.
        </p>
      ) : noChange ? (
        <p className="text-sm text-emerald-700">Already correct — nothing would change.</p>
      ) : (
        <div className="space-y-1 text-sm">
          {preview.would_add.length > 0 && (
            <p className="text-emerald-700">Would add: {preview.would_add.join(", ")}</p>
          )}
          {preview.would_remove.length > 0 && (
            <p className="text-red-700">Would remove: {preview.would_remove.join(", ")}</p>
          )}
        </div>
      )}
    </div>
  );
}
