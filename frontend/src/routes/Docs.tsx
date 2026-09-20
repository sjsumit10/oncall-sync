import { Link as LinkIcon, MessageSquare, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/page";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Step = { title: string; body: string };

function GuideCard({
  icon: Icon,
  title,
  description,
  steps,
  cta,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  steps: Step[];
  cta: { to: string; label: string };
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3 space-y-0">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-4.5" />
        </div>
        <div className="space-y-1">
          <CardTitle>{title}</CardTitle>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </CardHeader>
      <CardContent>
        <ol className="space-y-4">
          {steps.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground">
                {index + 1}
              </span>
              <div className="space-y-0.5 pt-0.5">
                <p className="text-sm font-medium text-foreground">{step.title}</p>
                <p className="text-sm text-muted-foreground">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <Link
          to={cta.to}
          className="mt-5 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          {cta.label} &rarr;
        </Link>
      </CardContent>
    </Card>
  );
}

export default function Docs() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Docs"
        description="How to connect your tools and keep on-call handles in sync."
      />

      <GuideCard
        icon={LinkIcon}
        title="1. Connect an on-call provider"
        description="Tell On-Call Sync where your schedules live."
        steps={[
          {
            title: "Open Connections",
            body: "Go to Connections in the left menu.",
          },
          {
            title: "Add PagerDuty",
            body: "Under \"On-call provider\", click Connect and approve the authorization request.",
          },
          {
            title: "Confirm it's healthy",
            body: "Once connected, the card shows a healthy status and your schedules are cached automatically. Use Refresh any time a schedule changes.",
          },
        ]}
        cta={{ to: "/connections", label: "Go to Connections" }}
      />

      <GuideCard
        icon={MessageSquare}
        title="2. Connect a chat provider"
        description="Tell On-Call Sync where to update handles and post handoff messages."
        steps={[
          {
            title: "Open Connections",
            body: "On the same Connections page, scroll to \"Chat provider\".",
          },
          {
            title: "Add Slack or Microsoft Teams",
            body: "Click Connect and approve the requested permissions. For Slack, approve both the app and user permissions so group membership can be updated.",
          },
          {
            title: "Pick a group and channel",
            body: "Once connected, a user group (Slack) or tag (Teams) can be kept in sync, and a channel can receive handoff announcements — both are chosen per rule in the next step.",
          },
        ]}
        cta={{ to: "/connections", label: "Go to Connections" }}
      />

      <GuideCard
        icon={Workflow}
        title="3. Create a sync rule"
        description="Map an on-call schedule to a chat group so the current on-call person is always tagged."
        steps={[
          {
            title: "Open Rules",
            body: "Go to Rules in the left menu and click New rule.",
          },
          {
            title: "Pick a schedule and escalation levels",
            body: "Choose the on-call schedule to follow, and which escalation levels (1-3) count as \"on call\".",
          },
          {
            title: "Pick a chat group",
            body: "Choose the Slack user group or Teams tag whose membership should always match who's on call.",
          },
          {
            title: "Optionally announce handoffs",
            body: "Turn on \"Notify on change\" and pick a channel to post a message whenever on-call changes. Add a fallback chat user for gaps when no one is on call.",
          },
          {
            title: "Save",
            body: "On-Call Sync syncs the rule automatically going forward. Check Activity to see run history and status for each rule.",
          },
        ]}
        cta={{ to: "/rules", label: "Go to Rules" }}
      />
    </div>
  );
}
