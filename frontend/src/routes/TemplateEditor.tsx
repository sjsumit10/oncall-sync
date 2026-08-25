import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Alert, Button } from "@/components/ui";
import { api } from "@/lib/api";
import type { MessagePreview } from "@/lib/types";

/**
 * Template editor with a live preview.
 *
 * Previews render against sample data rather than the live schedule: this fires
 * on every keystroke, and going to PagerDuty and Slack that often would be both
 * slow and rude.
 */
export function TemplateEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [preview, setPreview] = useState<MessagePreview | null>(null);

  const render = useMutation({
    mutationFn: (template: string) =>
      api.post<MessagePreview>("/rules/template/preview", {
        template: template.trim() ? template : null,
      }),
    onSuccess: setPreview,
  });

  // Debounced so typing does not fire a request per character.
  useEffect(() => {
    const timer = setTimeout(() => render.mutate(value), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const variables = Object.keys(preview?.variables ?? {});

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="mb-1 block text-sm font-medium text-slate-700">
          Handoff message
        </span>
        <textarea
          className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
          rows={4}
          value={value}
          placeholder="Leave blank to use the default message"
          onChange={(event) => onChange(event.target.value)}
        />
      </label>

      {variables.length > 0 && (
        <p className="text-xs text-slate-500">
          Available:{" "}
          {variables.map((name, index) => (
            <span key={name}>
              {index > 0 && ", "}
              <button
                type="button"
                className="font-mono text-slate-700 underline"
                title={preview?.variables[name]}
                onClick={() => onChange(`${value}{{ ${name} }}`)}
              >
                {`{{ ${name} }}`}
              </button>
            </span>
          ))}
        </p>
      )}

      {preview?.problems.map((problem) => <Alert key={problem}>{problem}</Alert>)}

      {preview && preview.problems.length === 0 && (
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">
            Preview
          </p>
          <pre className="whitespace-pre-wrap font-sans text-sm text-slate-900">
            {preview.text}
          </pre>
          {preview.blocks.length > 1 && (
            <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-500">
              Plus a context line with the schedule, handle and shift end.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function ResetTemplateButton({ onReset }: { onReset: () => void }) {
  return (
    <Button type="button" variant="ghost" onClick={onReset}>
      Use the default message
    </Button>
  );
}
