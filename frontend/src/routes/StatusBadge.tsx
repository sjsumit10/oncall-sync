const LABEL: Record<string, string> = {
  active: "Connected",
  needs_reauth: "Reconnect required",
  error: "Error",
};

const STYLE: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700",
  needs_reauth: "bg-amber-50 text-amber-800",
  error: "bg-red-50 text-red-700",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        STYLE[status] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {LABEL[status] ?? status}
    </span>
  );
}
