import { Alert } from "@/components/ui/alert";
import type { RulePreview } from "@/lib/types";

/** The dry run. Shares its evaluation with the reconciler, so this is what will happen. */
export function RulePreviewPanel({ preview }: { preview: RulePreview }) {
  const noChange =
    preview.would_write && preview.would_add.length === 0 && preview.would_remove.length === 0;

  return (
    <div className="mt-4 space-y-3 rounded-lg border border-border bg-muted/40 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium text-foreground">On call for</span>
        <span className="text-sm text-foreground">{preview.schedule_name}</span>
        {preview.next_change_at && (
          <span className="ml-auto text-xs text-muted-foreground">
            next handoff {new Date(preview.next_change_at).toLocaleString()}
          </span>
        )}
      </div>

      {preview.resolved.length > 0 && (
        <ul className="space-y-1">
          {preview.resolved.map((member) => (
            <li key={member.chat_user_id} className="text-sm text-foreground">
              {member.provider_user.name}
              <span className="text-muted-foreground">
                {" → "}
                {member.chat_user_name ?? member.chat_user_id}
              </span>
              {member.source === "manual" && (
                <span className="ml-2 text-xs text-muted-foreground/70">manually linked</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {preview.used_fallback && (
        <p className="text-sm text-warning">
          Using the fallback member — an empty group is not allowed.
        </p>
      )}

      {preview.problems.map((problem) => (
        <Alert key={problem}>{problem}</Alert>
      ))}

      {!preview.would_write ? (
        <p className="text-sm text-muted-foreground">The handle will be left exactly as it is.</p>
      ) : noChange ? (
        <p className="text-sm text-success">Already correct — nothing would change.</p>
      ) : (
        <div className="space-y-1 text-sm">
          {preview.would_add.length > 0 && (
            <p className="text-success">Would add: {preview.would_add.join(", ")}</p>
          )}
          {preview.would_remove.length > 0 && (
            <p className="text-destructive">Would remove: {preview.would_remove.join(", ")}</p>
          )}
        </div>
      )}
    </div>
  );
}
