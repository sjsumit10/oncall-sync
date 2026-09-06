import { ArrowRight, MessageSquare, RefreshCw, Workflow } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useSession } from "@/lib/auth";

const FEATURES = [
  {
    icon: RefreshCw,
    title: "Always up to date",
    description:
      "The moment a PagerDuty shift hands off, the Slack group updates with it — no cron job to babysit, no stale handle.",
  },
  {
    icon: MessageSquare,
    title: "One handle, zero guesswork",
    description:
      "@devops-on-call always resolves to whoever is actually on call. People and channels stay mapped by email, automatically.",
  },
  {
    icon: Workflow,
    title: "Drift-proof",
    description:
      "Someone hand-edits the group during an incident? The next sync repairs it silently — without faking a handoff announcement.",
  },
];

export default function Landing() {
  const { data: session } = useSession();

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Workflow className="size-4.5" />
            </div>
            <span className="text-sm font-semibold tracking-tight text-foreground">
              On-Call Sync
            </span>
          </div>

          <nav className="flex items-center gap-2">
            {session ? (
              <Button asChild size="sm">
                <Link to="/overview">Dashboard</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm">
                  <Link to="/login">Log in</Link>
                </Button>
                <Button asChild size="sm">
                  <Link to="/signup">Sign Up</Link>
                </Button>
              </>
            )}
          </nav>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden">
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage:
                "radial-gradient(circle at 15% 10%, hsl(var(--primary) / 0.12), transparent 45%), radial-gradient(circle at 85% 30%, hsl(var(--primary) / 0.08), transparent 40%)",
            }}
          />
          <div className="relative mx-auto max-w-3xl px-6 py-24 text-center sm:py-32">
            <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
              Whoever is on call is always{" "}
              <span className="text-primary">one mention away</span>
            </h1>
            <p className="mx-auto mt-5 max-w-xl text-lg text-muted-foreground">
              On-Call Sync keeps your Slack user groups mapped to the right PagerDuty schedule,
              automatically, so a handoff never leaves anyone in the dark.
            </p>
            <div className="mt-8 flex items-center justify-center gap-3">
              <Button asChild size="lg">
                <Link to={session ? "/overview" : "/signup"}>
                  {session ? "Go to dashboard" : "Get started free"}
                  <ArrowRight />
                </Link>
              </Button>
            </div>
          </div>
        </section>

        <section className="border-t border-border bg-muted/30">
          <div className="mx-auto grid max-w-5xl gap-6 px-6 py-20 sm:grid-cols-3">
            {FEATURES.map((feature) => (
              <Card key={feature.title} className="border-border/70 shadow-sm">
                <CardContent className="pt-6">
                  <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <feature.icon className="size-4.5" />
                  </div>
                  <h3 className="mt-4 text-sm font-semibold text-foreground">{feature.title}</h3>
                  <p className="mt-1.5 text-sm text-muted-foreground">{feature.description}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto max-w-6xl px-6 py-8 text-center text-xs text-muted-foreground">
          &copy; {new Date().getFullYear()} On-Call Sync
        </div>
      </footer>
    </div>
  );
}
