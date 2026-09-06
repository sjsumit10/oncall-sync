import {
  Activity as ActivityIcon,
  ChevronsUpDown,
  LayoutDashboard,
  LogOut,
  Plug,
  Settings as SettingsIcon,
  Users,
  Workflow,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useLogout, useSession } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/overview", label: "Overview", end: true, icon: LayoutDashboard },
  { to: "/rules", label: "Rules", end: false, icon: Workflow },
  { to: "/activity", label: "Activity", end: false, icon: ActivityIcon },
  { to: "/connections", label: "Connections", end: false, icon: Plug },
  { to: "/identities", label: "Identities", end: false, icon: Users },
  { to: "/settings", label: "Settings", end: false, icon: SettingsIcon },
];

export function AppLayout() {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="flex-1 md:pl-64">
        <div className="mx-auto max-w-5xl px-6 py-10 md:px-10">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Sidebar() {
  const { data: session } = useSession();
  const logout = useLogout();
  const initial = session?.user.name.trim().charAt(0).toUpperCase() || "?";

  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex">
      <div className="flex h-16 items-center gap-2 px-5">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Workflow className="size-4.5" />
        </div>
        <span className="text-sm font-semibold tracking-tight text-white">On-Call Sync</span>
      </div>

      <nav className="flex-1 space-y-0.5 px-3 py-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
              )
            }
          >
            <item.icon className="size-4 shrink-0" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-sidebar-border p-3">
        <DropdownMenu>
          <DropdownMenuTrigger className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-sidebar-accent/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-white">
              {initial}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-white">{session?.user.name}</p>
              <p className="truncate text-xs text-sidebar-foreground/60">
                {session?.organization.name}
              </p>
            </div>
            <ChevronsUpDown className="size-3.5 shrink-0 text-sidebar-foreground/50" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="top" className="w-56">
            <DropdownMenuLabel>
              Signed in as
              <p className="mt-0.5 truncate text-sm font-medium text-foreground">
                {session?.user.email}
              </p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:bg-destructive/10 focus:text-destructive"
              onClick={() => logout.mutate()}
            >
              <LogOut />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  );
}
