import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useLogout, useSession } from "@/lib/auth";
import { useIdleLogout } from "@/lib/useIdleLogout";

const IDLE_TIMEOUT_MS = 30 * 60 * 1000;

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: session, isPending } = useSession();
  const location = useLocation();
  const logout = useLogout();

  // Session-null re-renders this component, which is what actually redirects
  // below — the same reactivity the manual "Sign out" button relies on.
  useIdleLogout(!!session, IDLE_TIMEOUT_MS, () => logout.mutate());

  if (isPending) return <FullPageSpinner />;
  if (!session) {
    // Remember where they were headed so login can send them back.
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
}

export function FullPageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="size-6 animate-spin rounded-full border-2 border-muted border-t-primary" />
    </div>
  );
}
