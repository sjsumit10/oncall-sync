import { NavLink, Outlet } from "react-router-dom";

import { useLogout, useSession } from "@/lib/auth";
import { Button } from "./ui";

// Activity arrives in M7.
const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/rules", label: "Rules", end: false },
  { to: "/connections", label: "Connections", end: false },
  { to: "/identities", label: "Identities", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export function AppLayout() {
  const { data: session } = useSession();
  const logout = useLogout();

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3">
          <span className="font-semibold text-slate-900">On-Call Sync</span>
          <nav className="flex gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm ${
                    isActive ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
            <span>
              {session?.user.name} · {session?.organization.name}
            </span>
            <Button variant="ghost" onClick={() => logout.mutate()} disabled={logout.isPending}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
