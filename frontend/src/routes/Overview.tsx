import { Card } from "@/components/ui";
import { useSession } from "@/lib/auth";

export default function Overview() {
  const { data: session } = useSession();

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">
        Welcome, {session?.user.name.split(" ")[0]}
      </h1>
      <Card title="Next: connect your tools">
        <p className="text-sm text-slate-600">
          Connect PagerDuty and install the Slack app, then map a schedule to a user group so
          the handle always points at whoever is actually on call.
        </p>
        <p className="mt-3 text-sm text-slate-400">
          Connections and sync rules arrive in the next milestones.
        </p>
      </Card>
    </div>
  );
}
