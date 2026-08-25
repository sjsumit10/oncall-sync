import { Badge, type BadgeProps } from "@/components/ui/badge";

const LABEL: Record<string, string> = {
  active: "Connected",
  needs_reauth: "Reconnect required",
  error: "Error",
};

const VARIANT: Record<string, BadgeProps["variant"]> = {
  active: "success",
  needs_reauth: "warning",
  error: "destructive",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={VARIANT[status] ?? "secondary"} dot>
      {LABEL[status] ?? status}
    </Badge>
  );
}
