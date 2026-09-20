import {
  ArrowRight,
  Link2,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useSession } from "@/lib/auth";

const FEATURES = [
  {
    icon: RefreshCw,
    title: "Always up to date",
    description:
      "The moment a PagerDuty shift hands off, the Slack or Teams group updates with it — no cron job to babysit, no stale handle.",
  },
  {
    icon: MessageSquare,
    title: "One handle, zero guesswork",
    description:
      "@devops-on-call always resolves to whoever is actually on call. People and channels stay mapped by email, automatically.",
  },
  {
    icon: ShieldCheck,
    title: "Drift-proof",
    description:
      "Someone hand-edits the group during an incident? The next sync repairs it silently — without faking a handoff announcement.",
  },
];

const STEPS = [
  {
    title: "Connect PagerDuty",
    description: "Authorize once. Your schedules are read automatically from then on.",
  },
  {
    title: "Connect Slack or Teams",
    description: "Approve the app and pick the group, tag, or channel to keep in sync.",
  },
  {
    title: "Create a sync rule",
    description: "Map a schedule to a group. On-Call Sync takes it from there.",
  },
];

const INTEGRATIONS = ["PagerDuty", "Slack", "Microsoft Teams"];

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
            <div className="mx-auto mb-6 inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground shadow-sm">
              <Link2 className="size-3.5 text-primary" />
              PagerDuty &harr; Slack &amp; Microsoft Teams
            </div>
            <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
              Whoever is on call is always{" "}
              <span className="text-primary">one mention away</span>
            </h1>
            <p className="mx-auto mt-5 max-w-xl text-lg text-muted-foreground">
              On-Call Sync keeps your Slack or Teams group mapped to the right PagerDuty
              schedule, automatically, so a handoff never leaves anyone in the dark.
            </p>
            <div className="mt-8 flex items-center justify-center gap-3">
              <Button asChild size="lg">
                <Link to={session ? "/overview" : "/signup"}>
                  {session ? "Go to dashboard" : "Get started free"}
                  <ArrowRight />
                </Link>
              </Button>
            </div>
            <p className="mt-6 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Works with{" "}
              {INTEGRATIONS.map((name, index) => (
                <span key={name}>
                  <span className="text-foreground/80">{name}</span>
                  {index < INTEGRATIONS.length - 1 && " · "}
                </span>
              ))}
            </p>
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

        <section className="border-t border-border">
          <div className="mx-auto max-w-4xl px-6 py-20">
            <div className="text-center">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                Live in three steps
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                No infrastructure to run, nothing to maintain.
              </p>
            </div>
            <ol className="mt-12 grid gap-8 sm:grid-cols-3">
              {STEPS.map((step, index) => (
                <li key={step.title} className="text-center sm:text-left">
                  <span className="inline-flex size-8 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                    {index + 1}
                  </span>
                  <h3 className="mt-3 text-sm font-semibold text-foreground">{step.title}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{step.description}</p>
                </li>
              ))}
            </ol>
            <div className="mt-12 text-center">
              <Button asChild size="lg">
                <Link to={session ? "/overview" : "/signup"}>
                  {session ? "Go to dashboard" : "Get started free"}
                  <ArrowRight />
                </Link>
              </Button>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-2 px-6 py-8 text-center text-xs text-muted-foreground sm:flex-row sm:justify-between sm:text-left">
          <span>&copy; {new Date().getFullYear()} On-Call Sync</span>
          <span>Built for teams who'd rather trust an automated sync than a manual checklist.</span>
        </div>
      </footer>
    </div>
  );
}
