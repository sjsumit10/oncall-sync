import { useMutation } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
  const id = useId();

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
      <div className="space-y-1.5">
        <Label htmlFor={id}>Handoff message</Label>
        <Textarea
          id={id}
          className="font-mono"
          rows={4}
          value={value}
          placeholder="Leave blank to use the default message"
          onChange={(event) => onChange(event.target.value)}
        />
      </div>

      {variables.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Available:{" "}
          {variables.map((name, index) => (
            <span key={name}>
              {index > 0 && ", "}
              <button
                type="button"
                className="font-mono text-foreground underline underline-offset-4"
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
        <div className="rounded-md border border-border bg-background p-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Preview
          </p>
          <pre className="whitespace-pre-wrap font-sans text-sm text-foreground">
            {preview.text}
          </pre>
          {preview.blocks.length > 1 && (
            <p className="mt-2 border-t border-border pt-2 text-xs text-muted-foreground">
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
    <Button type="button" variant="outline" size="sm" onClick={onReset}>
      Use the default message
    </Button>
  );
}
